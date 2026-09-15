import sys
import json
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class TrainQueue(Atomic):
    """
    Atomic DEVS model representing onboard passengers for a single train.

    - Receives boarded passengers on boarded_in and stores them grouped by destination.
    - Receives train arrivals on train_arrival_in and schedules serial alighting for
      passengers whose destination matches the arriving station_id.
    - For each alighting passenger, writes exactly one JSONL record to stdout with
      event='passenger_exiting'. No DEVS output ports exist.
    """

    def __init__(self, name: str, parent: Coupled | None, station_names: dict, alight_dt_s: float):
        super().__init__(name)
        self.parent = parent

        self.station_names = dict(station_names) if station_names is not None else {}
        self.alight_dt_s = float(alight_dt_s)

        # Ports (locked contract)
        self.add_in_port(Port(dict, "boarded_in"))
        self.add_in_port(Port(dict, "train_arrival_in"))

        # State
        self.onboard_by_destination: dict[int, deque[dict]] = {}

        # Pending alighting batches (queue of (station_id, passengers_list))
        self._pending_batches: deque[tuple[int, list[dict]]] = deque()

        # Active batch
        self.active_arrival_time: float | None = None
        self.active_station_id: int | None = None
        self.active_queue: list[dict] | None = None
        self._active_index: int = 0  # next passenger index to alight (0-based)

        # Output staging for internal transition (stdout side effect in lambdaf)
        self._stdout_record_to_write: dict | None = None

    def _warn(self, msg: str) -> None:
        print(f"[TrainQueue] {msg}", file=sys.stderr, flush=True)

    def _station_str(self, station_id: int) -> str:
        if station_id in self.station_names:
            return str(self.station_names[station_id])
        self._warn(f"station_names missing station_id={station_id}; using fallback string")
        return str(station_id)

    def _effective_alight_dt(self) -> float:
        if self.alight_dt_s <= 0:
            self._warn(f"alight_dt_s={self.alight_dt_s} <= 0; treating as 0")
            return 0.0
        return self.alight_dt_s

    def _validate_station_id(self, station_id) -> bool:
        return isinstance(station_id, int) and 1 <= station_id <= 5

    def _enqueue_boarded(self, passenger: dict) -> None:
        dest = passenger.get("destination", None)
        if not self._validate_station_id(dest):
            self._warn(f"Invalid/missing destination in boarded passenger; dropping: {passenger}")
            return
        q = self.onboard_by_destination.get(dest)
        if q is None:
            q = deque()
            self.onboard_by_destination[dest] = q
        q.append(dict(passenger))

    def _capture_alighters(self, station_id: int) -> list[dict]:
        q = self.onboard_by_destination.get(station_id)
        if not q:
            return []
        passengers = list(q)
        q.clear()
        return passengers

    def _start_next_batch_if_possible(self) -> None:
        if self.active_queue is not None:
            return
        if not self._pending_batches:
            return

        station_id, passengers = self._pending_batches.popleft()
        self.active_station_id = station_id
        self.active_queue = passengers
        self._active_index = 0

        now = float(get_current_time())
        # Ensure nondecreasing time ordering vs any prior active batch that ended later.
        if self.active_arrival_time is None:
            self.active_arrival_time = now
        else:
            self.active_arrival_time = max(self.active_arrival_time, now)

        if len(self.active_queue) > 0:
            dt = self._effective_alight_dt()
            self.hold_in("ALIGHTING", dt)
        else:
            # Empty batch: immediately move on
            self.active_station_id = None
            self.active_queue = None
            self._active_index = 0
            if self._pending_batches:
                self._start_next_batch_if_possible()
            else:
                self.passivate("IDLE")

    def _schedule_arrival_batch(self, arrival_msg: dict) -> None:
        station_id = arrival_msg.get("station_id", None)
        if not self._validate_station_id(station_id):
            self._warn(f"Invalid/missing station_id in train_arrival_in; ignoring: {arrival_msg}")
            return

        passengers = self._capture_alighters(station_id)

        # Queue this batch; if currently idle, it may start immediately.
        self._pending_batches.append((station_id, passengers))

        if self.active_queue is None:
            # Establish base arrival time for this batch from current sim time
            self.active_arrival_time = float(get_current_time())
            self._start_next_batch_if_possible()

    def _prepare_next_stdout_record(self) -> None:
        # Called only when phase == ALIGHTING at an internal event time.
        if self.active_queue is None or self.active_station_id is None or self.active_arrival_time is None:
            self._stdout_record_to_write = None
            return

        if self._active_index >= len(self.active_queue):
            self._stdout_record_to_write = None
            return

        passenger = self.active_queue[self._active_index]
        completion_time = float(get_current_time())

        self._stdout_record_to_write = {
            "time": completion_time,
            "event": "passenger_exiting",
            "entity_type": "train_queue",
            "station_id": int(self.active_station_id),
            "station": self._station_str(int(self.active_station_id)),
            "payload": {
                "passenger_id": int(passenger.get("passenger_id")),
                "passenger_num": int(passenger.get("passenger_num")),
                "origin": int(passenger.get("origin")),
                "destination": int(passenger.get("destination")),
            },
        }

    def initialize(self):
        self.onboard_by_destination = {}
        self._pending_batches = deque()

        self.active_arrival_time = None
        self.active_station_id = None
        self.active_queue = None
        self._active_index = 0

        self._stdout_record_to_write = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # Preserve remaining time if already active
        if self.phase != "IDLE":
            self.continuef(e)

        # Boarded passengers can arrive any time; incorporate immediately.
        for passenger in self.input["boarded_in"].values:
            if isinstance(passenger, dict):
                self._enqueue_boarded(passenger)
            else:
                self._warn(f"Non-dict boarded_in message ignored: {passenger}")

        # Train arrivals trigger alighting capture and scheduling
        for arrival in self.input["train_arrival_in"].values:
            if isinstance(arrival, dict):
                self._schedule_arrival_batch(arrival)
            else:
                self._warn(f"Non-dict train_arrival_in message ignored: {arrival}")

        # If idle and work exists, start it.
        if self.phase == "IDLE" and (self.active_queue is None) and self._pending_batches:
            self.active_arrival_time = float(get_current_time())
            self._start_next_batch_if_possible()

    def lambdaf(self):
        # No DEVS outputs; only stdout side effect.
        if self.phase == "ALIGHTING":
            self._prepare_next_stdout_record()
            if self._stdout_record_to_write is not None:
                print(json.dumps(self._stdout_record_to_write), flush=True)

    def deltint(self):
        if self.phase == "ALIGHTING":
            # One passenger has just alighted (and was printed in lambdaf)
            if self.active_queue is None:
                self._stdout_record_to_write = None
                self.passivate("IDLE")
                return

            self._active_index += 1
            self._stdout_record_to_write = None

            if self._active_index < len(self.active_queue):
                dt = self._effective_alight_dt()
                self.hold_in("ALIGHTING", dt)
            else:
                # Batch complete
                self.active_station_id = None
                self.active_queue = None
                self._active_index = 0

                # If there are queued batches, start next immediately (no extra delay beyond its own dt)
                if self._pending_batches:
                    # Base time for next batch must not be earlier than now to preserve order
                    self.active_arrival_time = float(get_current_time())
                    self._start_next_batch_if_possible()
                else:
                    self.active_arrival_time = None
                    self.passivate("IDLE")
        else:
            # Any other phase: go idle
            self._stdout_record_to_write = None
            self.passivate("IDLE")

    def exit(self):
        # No termination IO required.
        pass