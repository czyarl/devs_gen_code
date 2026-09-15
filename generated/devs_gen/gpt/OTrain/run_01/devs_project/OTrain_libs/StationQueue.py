import json
import sys
from collections import deque

from xdevs.models import Atomic, Coupled, Port


class StationQueue(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        station_id: int,
        station_names: dict,
        service_dt_s: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.station_id = int(station_id)
        self.station_names = dict(station_names)
        self.service_dt_s = float(service_dt_s)

        # Ports (locked contract)
        self.add_in_port(Port(dict, "passenger_in"))
        self.add_in_port(Port(dict, "train_arrival_in"))
        self.add_out_port(Port(dict, "boarded_out"))

        # State
        self.fifo_queue: deque[dict] = deque()
        self.active_arrival_time: float | None = None
        self.next_board_time: float | None = None
        self.boarding_active: bool = False
        self.last_emitted_time: float = 0.0

        # Output staging for lambdaf()
        self._pending_boarded_msg: dict | None = None
        self._pending_stdout_record: dict | None = None
        self._pending_original_time: float | None = None

    def initialize(self):
        if self.service_dt_s <= 0:
            print(
                f"[StationQueue:{self.name}] WARNING: service_dt_s={self.service_dt_s} <= 0; "
                f"using default 0.025 to avoid zero-delay loop.",
                file=sys.stderr,
                flush=True,
            )
            self.service_dt_s = 0.025

        self.fifo_queue = deque()
        self.active_arrival_time = None
        self.next_board_time = None
        self.boarding_active = False
        self.last_emitted_time = 0.0

        self._pending_boarded_msg = None
        self._pending_stdout_record = None
        self._pending_original_time = None

        self.passivate("IDLE")

    def _is_valid_passenger(self, p: dict) -> bool:
        try:
            if int(p.get("origin")) != self.station_id:
                return False
            dest = p.get("destination")
            if not isinstance(dest, int):
                # allow int-like values but reject non-numeric
                dest = int(dest)
            if dest < 1 or dest > 5:
                return False
            if dest == self.station_id:
                return False
            return True
        except Exception:
            return False

    def _start_or_reset_boarding(self, arrival_time: float) -> None:
        if not self.fifo_queue:
            return

        if self.boarding_active:
            print(
                f"[StationQueue:{self.name}] INFO: rescheduling boarding due to new arrival "
                f"at station_id={self.station_id} arrival_time={arrival_time}.",
                file=sys.stderr,
                flush=True,
            )

        self.active_arrival_time = float(arrival_time)
        self.next_board_time = self.active_arrival_time + self.service_dt_s
        self.boarding_active = True

        now = float(arrival_time)
        sigma = max(0.0, self.next_board_time - now)
        self.hold_in("BOARDING", sigma)

    def deltext(self, e: float):
        # Preserve any existing timer if we remain boarding and do not reset schedule.
        was_boarding = self.phase == "BOARDING"
        remaining = max(0.0, self.ta() - e) if was_boarding else None

        # Enqueue passengers (validation)
        for passenger in self.input["passenger_in"].values:
            if self._is_valid_passenger(passenger):
                self.fifo_queue.append(dict(passenger))
            else:
                print(
                    f"[StationQueue:{self.name}] WARNING: rejected passenger for station_id={self.station_id}: {passenger}",
                    file=sys.stderr,
                    flush=True,
                )

        # Process train arrivals (may reset schedule)
        reset_by_arrival = False
        last_matching_arrival_time = None
        for notice in self.input["train_arrival_in"].values:
            try:
                if int(notice.get("station_id")) != self.station_id:
                    continue
                last_matching_arrival_time = float(notice.get("time"))
                reset_by_arrival = True
            except Exception:
                # Ignore malformed notices
                continue

        if reset_by_arrival and last_matching_arrival_time is not None:
            self._start_or_reset_boarding(last_matching_arrival_time)
            return

        # No schedule reset; keep or start if idle and already active? Boarding is only triggered by arrival.
        if was_boarding:
            # Continue existing schedule
            self.hold_in("BOARDING", remaining)
        else:
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "EMIT" and self._pending_boarded_msg is not None:
            # External IO to stdout (JSONL)
            if self._pending_stdout_record is not None:
                print(json.dumps(self._pending_stdout_record), flush=True)

            # DEVS output
            self.output["boarded_out"].add(dict(self._pending_boarded_msg))

    def deltint(self):
        if self.phase == "BOARDING":
            # Prepare one boarding output at the scheduled time.
            if not self.boarding_active or self.next_board_time is None or not self.fifo_queue:
                # Nothing to do; become passive.
                self.boarding_active = False
                self.active_arrival_time = None
                self.next_board_time = None
                self._pending_boarded_msg = None
                self._pending_stdout_record = None
                self._pending_original_time = None
                self.passivate("IDLE")
                return

            scheduled_t = float(self.next_board_time)
            passenger = dict(self.fifo_queue.popleft())

            t_out = scheduled_t
            if t_out < self.last_emitted_time:
                print(
                    f"[StationQueue:{self.name}] WARNING: nondecreasing time clamp: "
                    f"scheduled_t={scheduled_t} < last_emitted_time={self.last_emitted_time}. "
                    f"Clamping to {self.last_emitted_time}.",
                    file=sys.stderr,
                    flush=True,
                )
                t_out = self.last_emitted_time

            boarded_msg = {
                "time": t_out,
                "passenger_id": int(passenger["passenger_id"]),
                "passenger_num": int(passenger["passenger_num"]),
                "origin": int(passenger["origin"]),
                "destination": int(passenger["destination"]),
            }

            stdout_record = {
                "time": t_out,
                "event": "passenger_boarding",
                "entity_type": "station_queue",
                "station_id": int(self.station_id),
                "station": self.station_names.get(self.station_id, str(self.station_id)),
                "payload": {
                    "passenger_id": int(passenger["passenger_id"]),
                    "passenger_num": int(passenger["passenger_num"]),
                    "origin": int(passenger["origin"]),
                    "destination": int(passenger["destination"]),
                },
            }

            self._pending_boarded_msg = boarded_msg
            self._pending_stdout_record = stdout_record
            self._pending_original_time = scheduled_t
            self.last_emitted_time = t_out

            # Emit immediately at this internal time.
            self.hold_in("EMIT", 0.0)
            return

        if self.phase == "EMIT":
            # Clear pending output and schedule next boarding step if needed.
            original_t = self._pending_original_time
            self._pending_boarded_msg = None
            self._pending_stdout_record = None
            self._pending_original_time = None

            if not self.boarding_active or original_t is None:
                self.boarding_active = False
                self.active_arrival_time = None
                self.next_board_time = None
                self.passivate("IDLE")
                return

            if self.fifo_queue:
                self.next_board_time = float(original_t) + self.service_dt_s
                sigma = max(0.0, self.next_board_time - float(original_t))
                self.hold_in("BOARDING", sigma)
            else:
                self.boarding_active = False
                self.active_arrival_time = None
                self.next_board_time = None
                self.passivate("IDLE")
            return

        # Fallback
        self.passivate("IDLE")

    def exit(self):
        pass