import sys
import json
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class StationQueue(Atomic):
    """
    Per-station FIFO queue and serial boarding processor.

    Responsibilities:
    - Validate and enqueue incoming passenger dicts for this station_id.
    - On matching train arrival, schedule serial boarding at times:
        arrival_time + k*step_s, k=1,2,3,... until queue empties.
    - For each boarded passenger: emit DEVS output on boarded_passenger_out AND
      write one JSONL passenger_boarding record to stdout.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        station_id: int,
        station_names: dict,
        step_s: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.station_id = station_id
        self.station_names = station_names
        self.step_s = float(step_s)

        self.add_in_port(Port(dict, "passenger_in"))
        self.add_in_port(Port(dict, "train_arrival_in"))
        self.add_out_port(Port(dict, "boarded_passenger_out"))

        # State (initialized in initialize)
        self.fifo_queue: deque[dict] | None = None
        self.active_boarding: bool = False
        self.current_arrival_time: float | None = None
        self.board_index: int = 0
        self.pending_board_passenger: dict | None = None
        self._pending_board_time: float | None = None

    def _warn(self, msg: str) -> None:
        print(f"[StationQueue:{self.name} station_id={self.station_id}] {msg}", file=sys.stderr, flush=True)

    def _is_valid_passenger(self, p: dict) -> bool:
        try:
            origin = p["origin"]
            destination = p["destination"]
            _ = p["passenger_id"]
            _ = p["passenger_num"]
        except Exception:
            return False

        if origin != self.station_id:
            return False
        if not isinstance(destination, int):
            return False
        if destination < 1 or destination > 5:
            return False
        if destination == origin:
            return False
        return True

    def _write_boarding_jsonl(self, t_fire: float, passenger: dict) -> None:
        station_name = self.station_names.get(self.station_id, str(self.station_id))
        record = {
            "time": float(t_fire),
            "event": "passenger_boarding",
            "entity_type": "station_queue",
            "station_id": int(self.station_id),
            "station": station_name,
            "payload": {
                "passenger_id": int(passenger["passenger_id"]),
                "passenger_num": int(passenger["passenger_num"]),
                "origin": int(passenger["origin"]),
                "destination": int(passenger["destination"]),
            },
        }
        print(json.dumps(record), flush=True)

    def _schedule_next_boarding_from_now(self) -> None:
        """
        Schedule the next internal event based on current_arrival_time and board_index.
        Assumes active_boarding is True and fifo_queue is not empty.
        """
        if self.current_arrival_time is None:
            self._warn("Internal error: current_arrival_time is None while active_boarding.")
            self.passivate("PASSIVE")
            return

        if self.step_s <= 0.0:
            # Preferred behavior per contract: treat as configuration error and never schedule boarding.
            self._warn(f"Configuration error: step_s={self.step_s} <= 0; boarding will not be scheduled.")
            self.active_boarding = False
            self.passivate("PASSIVE")
            return

        t_next = float(self.current_arrival_time + self.board_index * self.step_s)
        now = float(get_current_time())
        sigma = max(0.0, t_next - now)
        self._pending_board_time = t_next
        self.hold_in("BOARDING", sigma)

    def initialize(self):
        self.fifo_queue = deque()
        self.active_boarding = False
        self.current_arrival_time = None
        self.board_index = 0
        self.pending_board_passenger = None
        self._pending_board_time = None
        self.passivate("PASSIVE")

    def deltext(self, e: float):
        # Preserve remaining time if already scheduled.
        if self.phase != "PASSIVE":
            self.continuef(e)

        # Handle passenger arrivals (can happen anytime).
        for passenger in self.input["passenger_in"].values:
            if not isinstance(passenger, dict):
                self._warn(f"Rejected passenger: expected dict, got {type(passenger).__name__}.")
                continue

            if self._is_valid_passenger(passenger):
                self.fifo_queue.append(dict(passenger))
            else:
                # Optional warning; never JSONL.
                try:
                    self._warn(
                        "Rejected passenger due to validation failure: "
                        f"origin={passenger.get('origin')} destination={passenger.get('destination')}."
                    )
                except Exception:
                    self._warn("Rejected passenger due to validation failure (unreadable payload).")

        # Handle train arrivals.
        for arrival in self.input["train_arrival_in"].values:
            if not isinstance(arrival, dict):
                self._warn(f"Ignored train arrival: expected dict, got {type(arrival).__name__}.")
                continue

            try:
                station_id = int(arrival["station_id"])
                arrival_time = float(arrival["time"])
                _ = arrival["direction"]
            except Exception:
                self._warn("Ignored train arrival: missing/invalid fields.")
                continue

            if station_id != self.station_id:
                # Ignore other stations.
                continue

            # Matching arrival triggers (re)base boarding schedule.
            self.current_arrival_time = arrival_time
            self.board_index = 1

            if len(self.fifo_queue) == 0:
                self.active_boarding = False
                self.pending_board_passenger = None
                self._pending_board_time = None
                self.passivate("PASSIVE")
            else:
                self.active_boarding = True
                self.pending_board_passenger = None
                self._schedule_next_boarding_from_now()

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self.pending_board_passenger is not None:
            self.output["boarded_passenger_out"].add(dict(self.pending_board_passenger))

    def deltint(self):
        if self.phase == "BOARDING":
            # At the scheduled boarding time, pop one passenger and produce outputs.
            if not self.active_boarding:
                self.passivate("PASSIVE")
                return

            if self.fifo_queue is None or len(self.fifo_queue) == 0:
                # Unexpected empty queue: cancel.
                self.active_boarding = False
                self.current_arrival_time = None
                self.board_index = 0
                self.pending_board_passenger = None
                self._pending_board_time = None
                self.passivate("PASSIVE")
                return

            passenger = self.fifo_queue.popleft()
            t_fire = self._pending_board_time
            if t_fire is None:
                # Fallback to current time if something went wrong; should not happen.
                t_fire = float(get_current_time())

            # Required external IO: one JSONL record per boarded passenger.
            self._write_boarding_jsonl(t_fire, passenger)

            # Prepare DEVS output for lambdaf().
            self.pending_board_passenger = dict(passenger)

            # Advance k for next passenger in this arrival-triggered sequence.
            self.board_index += 1

            # Emit DEVS output at the same simulation time (0-delay output phase).
            self.hold_in("OUTPUT_READY", 0.0)

        elif self.phase == "OUTPUT_READY":
            # Clear emitted payload and schedule next boarding if any.
            self.pending_board_passenger = None

            if not self.active_boarding:
                self.current_arrival_time = None
                self.board_index = 0
                self._pending_board_time = None
                self.passivate("PASSIVE")
                return

            if self.fifo_queue is not None and len(self.fifo_queue) > 0:
                self._schedule_next_boarding_from_now()
            else:
                # End sequence; remain passive until next matching arrival.
                self.active_boarding = False
                self.current_arrival_time = None
                self.board_index = 0
                self._pending_board_time = None
                self.passivate("PASSIVE")
        else:
            self.passivate("PASSIVE")

    def exit(self):
        # No required finalization output.
        pass