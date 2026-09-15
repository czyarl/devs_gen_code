import sys
import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class StationQueue(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        station_id: int,
        station_names: dict,
        board_dt_s: float,
    ):
        super().__init__(name)
        self.parent = parent

        self.station_id = station_id
        self.station_names = station_names
        self.board_dt_s = float(board_dt_s)

        self.add_in_port(Port(dict, "passenger_in"))
        self.add_in_port(Port(dict, "train_arrival_in"))
        self.add_out_port(Port(dict, "boarded_out"))

        # State (initialized in initialize)
        self.waiting_fifo = None
        self.boarding_active = None
        self.session_base_arrival_time = None
        self.next_board_time = None
        self.last_emitted_time = None
        self._to_board = None  # prepared passenger payload to emit at next internal event

    def initialize(self):
        self.waiting_fifo = deque()
        self.boarding_active = False
        self.session_base_arrival_time = None
        self.next_board_time = None
        self.last_emitted_time = 0.0
        self._to_board = None
        self.passivate("IDLE")

    def _warn(self, msg: str) -> None:
        print(f"[StationQueue station_id={self.station_id}] {msg}", file=sys.stderr, flush=True)

    def _is_valid_passenger(self, msg: object) -> bool:
        if not isinstance(msg, dict):
            self._warn(f"Rejected passenger: not a dict: {msg!r}")
            return False

        required = ("time", "passenger_id", "passenger_num", "origin", "destination")
        for k in required:
            if k not in msg:
                self._warn(f"Rejected passenger: missing key '{k}': {msg!r}")
                return False

        origin = msg.get("origin")
        dest = msg.get("destination")
        if origin != self.station_id:
            self._warn(f"Rejected passenger: origin {origin!r} != station_id {self.station_id}: {msg!r}")
            return False

        if not isinstance(dest, int) or not (1 <= dest <= 5) or dest == origin:
            self._warn(f"Rejected passenger: invalid destination {dest!r} for origin {origin}: {msg!r}")
            return False

        return True

    def _arrival_time_from_msg(self, msg: dict) -> float:
        t_now = float(get_current_time())
        if isinstance(msg, dict) and "time" in msg:
            try:
                return float(msg["time"])
            except (TypeError, ValueError):
                self._warn(f"Malformed time in train arrival; using current time. msg={msg!r}")
                return t_now
        return t_now

    def _maybe_start_or_reset_session(self, arrival_time: float) -> None:
        # Only schedule boarding if there is someone waiting.
        if not self.waiting_fifo:
            self.boarding_active = False
            self.session_base_arrival_time = None
            self.next_board_time = None
            self._to_board = None
            self.passivate("IDLE")
            return

        if not self.boarding_active:
            self.boarding_active = True
            self.session_base_arrival_time = arrival_time
            self.next_board_time = arrival_time + self.board_dt_s
            delay = max(0.0, self.next_board_time - float(get_current_time()))
            self.hold_in("BOARDING", delay)
            return

        # If already active, only supersede if strictly later than current base arrival time.
        if self.session_base_arrival_time is None or arrival_time > float(self.session_base_arrival_time):
            self.session_base_arrival_time = arrival_time
            self.next_board_time = arrival_time + self.board_dt_s
            delay = max(0.0, self.next_board_time - float(get_current_time()))
            self.hold_in("BOARDING", delay)

    def deltext(self, e: float):
        # Preserve remaining time if already scheduled.
        was_active = self.phase == "BOARDING"
        remaining = max(0.0, self.ta() - e) if was_active else None

        # Process passenger arrivals
        for p in self.input["passenger_in"].values:
            if self._is_valid_passenger(p):
                # Store a shallow copy to avoid external mutation.
                self.waiting_fifo.append(
                    {
                        "time": float(p["time"]),
                        "passenger_id": int(p["passenger_id"]),
                        "passenger_num": int(p["passenger_num"]),
                        "origin": int(p["origin"]),
                        "destination": int(p["destination"]),
                    }
                )

        # Process train arrivals
        for a in self.input["train_arrival_in"].values:
            if not isinstance(a, dict):
                self._warn(f"Ignored train arrival: not a dict: {a!r}")
                continue
            if a.get("station_id") != self.station_id:
                continue
            arrival_time = self._arrival_time_from_msg(a)
            self._maybe_start_or_reset_session(arrival_time)

        # If we were active and didn't reset/start a new timer above, preserve the existing one.
        # (A reset/start above would have called hold_in already.)
        if was_active and self.phase == "BOARDING":
            # Only preserve if next_board_time still corresponds to the existing schedule.
            self.hold_in("BOARDING", remaining)

        # If idle and no session started, remain idle.
        if self.phase != "BOARDING" and not self.boarding_active:
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase != "BOARDING":
            return
        if self._to_board is None:
            return

        # Emit DEVS boarded passenger message
        self.output["boarded_out"].add(dict(self._to_board))

        # Emit stdout JSONL passenger_boarding record
        t = float(self._to_board["time"])
        if t < float(self.last_emitted_time):
            t = float(self.last_emitted_time)

        record = {
            "time": float(t),
            "event": "passenger_boarding",
            "entity_type": "station_queue",
            "station_id": int(self.station_id),
            "station": str(self.station_names[int(self.station_id)]),
            "payload": {
                "passenger_id": int(self._to_board["passenger_id"]),
                "passenger_num": int(self._to_board["passenger_num"]),
                "origin": int(self._to_board["origin"]),
                "destination": int(self._to_board["destination"]),
            },
        }
        print(json.dumps(record), flush=True)
        self.last_emitted_time = float(t)

    def deltint(self):
        if self.phase != "BOARDING":
            self.passivate("IDLE")
            return

        # We have just completed a scheduled boarding completion time.
        now = float(get_current_time())

        # Clear the previously emitted payload (if any).
        self._to_board = None

        if not self.waiting_fifo:
            # Empty queue at completion: cancel further boarding.
            self.boarding_active = False
            self.session_base_arrival_time = None
            self.next_board_time = None
            self.passivate("IDLE")
            return

        # Pop next passenger in FIFO and schedule immediate output at this internal event time.
        passenger = self.waiting_fifo.popleft()

        # Compute completion time: it should be the scheduled next_board_time; if missing, use now.
        completion_time = self.next_board_time if self.next_board_time is not None else now
        try:
            completion_time = float(completion_time)
        except (TypeError, ValueError):
            completion_time = now

        # Clamp to nondecreasing print times for this model (and keep DEVS message consistent).
        if completion_time < float(self.last_emitted_time):
            completion_time = float(self.last_emitted_time)

        self._to_board = {
            "time": float(completion_time),
            "passenger_id": int(passenger["passenger_id"]),
            "passenger_num": int(passenger["passenger_num"]),
            "origin": int(passenger["origin"]),
            "destination": int(passenger["destination"]),
        }

        # Prepare next boarding completion time for subsequent passenger in this session.
        self.next_board_time = float(completion_time) + self.board_dt_s

        # Emit output immediately (sigma=0) then schedule next completion relative to absolute time.
        # After the immediate output, deltint() will be called again; we then schedule the delay.
        if self.phase == "BOARDING" and self.sigma != 0.0:
            # Not expected in normal flow; ensure immediate output.
            self.hold_in("BOARDING", 0.0)
            return

        # We are in the post-output internal transition (after sigma=0 event).
        # If _to_board is set, we need a zero-delay output first.
        if self._to_board is not None and self.sigma != 0.0:
            self.hold_in("BOARDING", 0.0)
            return

        # If sigma==0, this deltint is being called after lambdaf for that output.
        # Schedule next completion if there are still passengers waiting; otherwise stay active but idle.
        if self.waiting_fifo:
            delay = max(0.0, float(self.next_board_time) - float(get_current_time()))
            self.hold_in("BOARDING", delay)
            self.boarding_active = True
        else:
            self.boarding_active = False
            self.session_base_arrival_time = None
            self.next_board_time = None
            self.passivate("IDLE")

    def exit(self):
        pass