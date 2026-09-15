"""TrainQueue atomic DEVS model (xdevs.py).

Maintains onboard passengers grouped by destination and emits JSONL
`passenger_exiting` records to stdout when passengers alight after train arrivals.
"""

import sys
import json
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class TrainQueue(Atomic):
    def __init__(self, name: str, parent: Coupled | None, station_names: dict, step_s: float):
        super().__init__(name)
        self.parent = parent

        # Config
        self.station_names = station_names
        self.step_s = step_s

        # Ports (locked contract)
        self.add_in_port(Port(dict, "boarded_passenger_in"))
        self.add_in_port(Port(dict, "train_arrival_in"))

        # State
        self.onboard_by_destination: dict[int, deque] = {}
        self.pending_exits: list[tuple[float, int, dict, int]] = []
        self._next_seq: int = 0

    def initialize(self):
        self.onboard_by_destination = {sid: deque() for sid in (1, 2, 3, 4, 5)}
        self.pending_exits = []
        self._next_seq = 0
        self.passivate("IDLE")

    # -------------------------
    # Validation helpers
    # -------------------------
    @staticmethod
    def _is_int_in_range(x, lo: int, hi: int) -> bool:
        return isinstance(x, int) and lo <= x <= hi

    def _validate_passenger(self, msg) -> bool:
        if not isinstance(msg, dict):
            return False
        required = ("passenger_id", "passenger_num", "origin", "destination")
        if any(k not in msg for k in required):
            return False
        if not isinstance(msg["passenger_id"], int):
            return False
        if not isinstance(msg["passenger_num"], int):
            return False
        origin = msg["origin"]
        dest = msg["destination"]
        if not self._is_int_in_range(origin, 1, 5):
            return False
        if not self._is_int_in_range(dest, 1, 5):
            return False
        if dest == origin:
            return False
        return True

    def _validate_arrival(self, msg) -> tuple[bool, float, int]:
        if not isinstance(msg, dict):
            return (False, 0.0, 0)
        if "time" not in msg or "station_id" not in msg or "direction" not in msg:
            return (False, 0.0, 0)

        t = msg["time"]
        s = msg["station_id"]

        if not isinstance(t, (int, float)):
            return (False, 0.0, 0)
        t = float(t)
        if t < 0.0:
            return (False, 0.0, 0)

        if not self._is_int_in_range(s, 1, 5):
            return (False, 0.0, 0)

        now = get_current_time()
        if t < now:
            return (False, t, s)

        return (True, t, s)

    # -------------------------
    # Scheduling
    # -------------------------
    def _reschedule_from_pending(self) -> None:
        if not self.pending_exits:
            self.passivate("IDLE")
            return
        now = get_current_time()
        next_time = min(exit_time for exit_time, _, _, _ in self.pending_exits)
        self.hold_in("WAITING", max(0.0, next_time - now))

    # -------------------------
    # DEVS transitions
    # -------------------------
    def deltext(self, e: float):
        now = get_current_time()

        # Boarded passengers: store only (no stdout)
        for msg in self.input["boarded_passenger_in"].values:
            if not self._validate_passenger(msg):
                print(f"[TrainQueue] Ignoring invalid boarded passenger: {msg!r}",
                      file=sys.stderr, flush=True)
                continue
            dest = msg["destination"]
            self.onboard_by_destination[dest].append(dict(msg))

        # Arrivals: schedule exits
        for msg in self.input["train_arrival_in"].values:
            ok, t_arrival, station_id = self._validate_arrival(msg)
            if not ok:
                # If time earlier than now, it's invalid per contract; ignore.
                if isinstance(msg, dict) and "time" in msg:
                    print(f"[TrainQueue] Ignoring invalid arrival (time={msg.get('time')}, now={now}): {msg!r}",
                          file=sys.stderr, flush=True)
                else:
                    print(f"[TrainQueue] Ignoring invalid arrival: {msg!r}",
                          file=sys.stderr, flush=True)
                continue

            if self.step_s < 0:
                print(f"[TrainQueue] Invalid configuration step_s={self.step_s}; not scheduling exits.",
                      file=sys.stderr, flush=True)
                continue

            q = self.onboard_by_destination[station_id]
            n = len(q)
            if n == 0:
                continue

            # Remove immediately from onboard storage
            passengers = [q.popleft() for _ in range(n)]

            # Schedule exits in FIFO order
            step = float(self.step_s)
            for i, passenger in enumerate(passengers, start=1):
                exit_time = t_arrival + (i * step)
                self.pending_exits.append((exit_time, station_id, passenger, self._next_seq))
                self._next_seq += 1

        # Ensure we don't strand the next due exit
        self._reschedule_from_pending()

    def lambdaf(self):
        if self.phase != "WAITING":
            return

        now = get_current_time()

        # Emit all exits due at or before now, in deterministic order:
        # sort by (exit_time, seq)
        due = [(t, s, p, seq) for (t, s, p, seq) in self.pending_exits if t <= now]
        if not due:
            return

        due.sort(key=lambda x: (x[0], x[3]))
        for exit_time, station_id, passenger_payload, _ in due:
            station = self.station_names.get(station_id, str(station_id))
            record = {
                "time": float(exit_time),
                "event": "passenger_exiting",
                "entity_type": "train_queue",
                "station_id": int(station_id),
                "station": station,
                "payload": {
                    "passenger_id": int(passenger_payload["passenger_id"]),
                    "passenger_num": int(passenger_payload["passenger_num"]),
                    "origin": int(passenger_payload["origin"]),
                    "destination": int(passenger_payload["destination"]),
                },
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        now = get_current_time()
        # Remove all exits that are due (<= now)
        self.pending_exits = [
            (t, s, p, seq)
            for (t, s, p, seq) in self.pending_exits
            if t > now
        ]
        self._reschedule_from_pending()

    def exit(self):
        # No required finalization output.
        pass