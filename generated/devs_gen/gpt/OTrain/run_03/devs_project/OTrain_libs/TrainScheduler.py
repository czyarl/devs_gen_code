import sys
import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class TrainScheduler(Atomic):
    """
    Atomic DEVS model that autonomously emits train arrival notifications
    following a repeating route sequence, starting at t=0.0.

    External IO:
      - stdout: JSONL train_arrival records (ONLY JSON objects)
      - stderr: diagnostics/warnings only
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        station_names: dict,
        travel_interval_s: float,
        route_sequence: list,
    ):
        super().__init__(name)
        self.parent = parent

        # Config/state required by contract
        self.station_names = station_names
        self.travel_interval_s = float(travel_interval_s)
        self.route_sequence = route_sequence

        self.next_index: int = 0
        self.next_time: float = 0.0

        # Prepared payload for the next emission (must exist before lambdaf runs)
        self._pending_arrival: dict | None = None
        self._pending_stdout_record: dict | None = None

        # Ports
        self.add_out_port(Port(dict, "train_arrival_out"))

    def initialize(self):
        self.next_index = 0
        self.next_time = 0.0
        self._pending_arrival = None
        self._pending_stdout_record = None

        if self.travel_interval_s == 0.0:
            print(
                f"[{self.name}] WARNING: travel_interval_s == 0.0 is invalid; "
                "remaining passive to avoid zero-time infinite loop.",
                file=sys.stderr,
                flush=True,
            )
            self.passivate("CONFIG_ERROR")
            return

        if not isinstance(self.route_sequence, list) or len(self.route_sequence) == 0:
            print(
                f"[{self.name}] WARNING: route_sequence is empty/invalid; remaining passive.",
                file=sys.stderr,
                flush=True,
            )
            self.passivate("CONFIG_ERROR")
            return

        # Schedule first internal event at t=0.0 (arrival for route_sequence[0]).
        self._prepare_next_emission()
        self.hold_in("EMIT", 0.0)

    def deltext(self, e: float):
        # No input ports; ignore any external events.
        return None

    def lambdaf(self):
        if self.phase != "EMIT":
            return
        if self._pending_arrival is None or self._pending_stdout_record is None:
            # Should not happen; avoid emitting malformed output.
            print(
                f"[{self.name}] WARNING: EMIT phase without prepared payload; suppressing output.",
                file=sys.stderr,
                flush=True,
            )
            return

        # DEVS output port emission (exactly one per valid stop)
        self.output["train_arrival_out"].add(dict(self._pending_arrival))

        # External IO: stdout JSONL (exactly one record per valid stop)
        print(json.dumps(self._pending_stdout_record), flush=True)

    def deltint(self):
        if self.phase != "EMIT":
            self.passivate()
            return

        # Advance absolute time and route index for the next stop
        self.next_time = float(self.next_time) + float(self.travel_interval_s)
        self.next_index = (self.next_index + 1) % len(self.route_sequence)

        # Prepare next emission; if invalid, it will schedule a SKIP that advances time.
        self._prepare_next_emission()

        # If we prepared a valid emission, schedule it after travel_interval_s.
        # If we prepared a skip, also schedule after travel_interval_s.
        self.hold_in("EMIT", float(self.travel_interval_s))

    def exit(self):
        # No required finalization output.
        pass

    def _prepare_next_emission(self):
        """
        Prepare the next arrival emission (DEVS payload + stdout record) for the
        stop at (next_time, route_sequence[next_index]).

        If the stop entry is invalid, prepare a "skip" by setting pending payloads
        to None and logging to stderr. Time progression is preserved by deltint().
        """
        # Ensure next_time is non-negative float
        try:
            t = float(self.next_time)
        except Exception:
            t = 0.0

        stop = None
        try:
            stop = self.route_sequence[self.next_index]
        except Exception:
            stop = None

        # Validate stop structure
        if not isinstance(stop, dict):
            self._pending_arrival = None
            self._pending_stdout_record = None
            print(
                f"[{self.name}] WARNING: invalid stop entry at index {self.next_index}: "
                f"expected dict, got {type(stop).__name__}; skipping emission at t={t}.",
                file=sys.stderr,
                flush=True,
            )
            return

        station_id = stop.get("station_id", None)
        direction = stop.get("direction", None)

        valid = True
        if not isinstance(station_id, int) or not (1 <= station_id <= 5):
            valid = False
        if station_id not in self.station_names:
            valid = False
        if direction not in (0, 1):
            valid = False

        if not valid:
            self._pending_arrival = None
            self._pending_stdout_record = None
            print(
                f"[{self.name}] WARNING: invalid stop at index {self.next_index} "
                f"(station_id={station_id}, direction={direction}); skipping emission at t={t}.",
                file=sys.stderr,
                flush=True,
            )
            return

        station_str = self.station_names[station_id]

        # Prepare DEVS payload (port schema)
        self._pending_arrival = {
            "time": t,
            "station_id": station_id,
            "direction": direction,
        }

        # Prepare stdout JSONL record (required schema)
        self._pending_stdout_record = {
            "time": t,
            "event": "train_arrival",
            "entity_type": "train",
            "station_id": station_id,
            "station": station_str,
            "payload": {
                "station": station_id,
                "direction": direction,
            },
        }