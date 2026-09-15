import sys
import json

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Train(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        station_names: dict,
        travel_interval_s: int,
        initial_train_station_id: int,
        initial_train_direction: int,
        route_sequence: list,
    ):
        super().__init__(name)
        self.parent = parent

        # Config
        self.station_names = station_names
        self.travel_interval_s = travel_interval_s
        self.initial_train_station_id = initial_train_station_id
        self.initial_train_direction = initial_train_direction
        self.route_sequence = route_sequence

        # Ports
        self.add_out_port(Port(dict, "arrival_out"))
        self.add_out_port(Port(dict, "arrival_to_train_queue_out"))

        # State
        self.i: int = 0
        self.next_arrival_time: float = 0.0
        self.last_emitted_time: float | None = None

        # Prepared payload for lambdaf()
        self._pending_arrival_payload: dict | None = None
        self._pending_stdout_record: dict | None = None

    def initialize(self):
        self.i = 0
        self.next_arrival_time = 0.0
        self.last_emitted_time = None
        self._pending_arrival_payload = None
        self._pending_stdout_record = None

        if not self.route_sequence:
            print(
                f"[Train:{self.name}] ERROR: route_sequence is empty; model will remain passive.",
                file=sys.stderr,
                flush=True,
            )
            self.passivate("PASSIVE")
            return

        # Validate initial stop mismatch policy (route_sequence[0] is authoritative)
        first = self.route_sequence[0]
        first_station = first.get("station_id", None) if isinstance(first, dict) else None
        first_dir = first.get("direction", None) if isinstance(first, dict) else None
        if first_station != self.initial_train_station_id or first_dir != self.initial_train_direction:
            print(
                f"[Train:{self.name}] WARNING: initial_train_station_id/direction "
                f"({self.initial_train_station_id},{self.initial_train_direction}) "
                f"mismatch with route_sequence[0] ({first_station},{first_dir}); "
                f"using route_sequence[0] as authoritative first stop.",
                file=sys.stderr,
                flush=True,
            )

        # Ready to emit first arrival at t=0.0
        self.hold_in("EMIT_ARRIVAL", 0.0)

    def deltext(self, e: float):
        # No input ports; ignore.
        return None

    def _validate_stop(self, stop, idx: int) -> tuple[bool, int | None, int | None]:
        if not isinstance(stop, dict):
            print(
                f"[Train:{self.name}] ERROR: route_sequence[{idx}] is not a dict: {stop!r}",
                file=sys.stderr,
                flush=True,
            )
            return False, None, None

        if "station_id" not in stop or "direction" not in stop:
            print(
                f"[Train:{self.name}] ERROR: route_sequence[{idx}] missing keys; "
                f"required ('station_id','direction'): {stop!r}",
                file=sys.stderr,
                flush=True,
            )
            return False, None, None

        station_id = stop.get("station_id")
        direction = stop.get("direction")

        if not isinstance(station_id, int) or station_id < 1 or station_id > 5:
            print(
                f"[Train:{self.name}] ERROR: route_sequence[{idx}] invalid station_id {station_id!r}; "
                f"expected int in 1..5. stop={stop!r}",
                file=sys.stderr,
                flush=True,
            )
            return False, None, None

        if not isinstance(direction, int) or direction not in (0, 1):
            print(
                f"[Train:{self.name}] ERROR: route_sequence[{idx}] invalid direction {direction!r}; "
                f"expected int in {{0,1}}. stop={stop!r}",
                file=sys.stderr,
                flush=True,
            )
            return False, None, None

        return True, station_id, direction

    def _prepare_emission(self):
        """Prepare DEVS payload and stdout record for the current stop index at current sim time."""
        now = float(get_current_time())

        # Defensive monotonicity check (should never fail with correct scheduling)
        if self.last_emitted_time is not None and now < self.last_emitted_time:
            print(
                f"[Train:{self.name}] ERROR: non-monotonic emission time: now={now} < last={self.last_emitted_time}. "
                f"Suppressing stdout emission for this step.",
                file=sys.stderr,
                flush=True,
            )
            suppress_stdout = True
        else:
            suppress_stdout = False

        stop = self.route_sequence[self.i]
        ok, station_id, direction = self._validate_stop(stop, self.i)
        if not ok:
            # Skip emitting outputs for this stop
            self._pending_arrival_payload = None
            self._pending_stdout_record = None
            # Still update last_emitted_time to preserve monotonicity expectations for future checks
            self.last_emitted_time = now
            return

        payload = {"time": now, "station_id": station_id, "direction": direction}
        self._pending_arrival_payload = payload

        station_str = self.station_names.get(station_id)
        if station_str is None:
            station_str = "UNKNOWN"
            print(
                f"[Train:{self.name}] WARNING: station_names missing station_id={station_id}; using 'UNKNOWN' in stdout record.",
                file=sys.stderr,
                flush=True,
            )

        if suppress_stdout:
            self._pending_stdout_record = None
        else:
            self._pending_stdout_record = {
                "time": now,
                "event": "train_arrival",
                "entity_type": "train",
                "station_id": station_id,
                "station": station_str,
                "payload": {"station": station_id, "direction": direction},
            }

        self.last_emitted_time = now

    def lambdaf(self):
        if self.phase != "EMIT_ARRIVAL":
            return

        # Prepare emissions using the actual simulation time at lambdaf()
        self._prepare_emission()

        # Emit DEVS outputs if valid stop
        if self._pending_arrival_payload is not None:
            self.output["arrival_out"].add(dict(self._pending_arrival_payload))
            self.output["arrival_to_train_queue_out"].add(dict(self._pending_arrival_payload))

        # Emit stdout JSONL exactly once per stop arrival when valid and monotonic
        if self._pending_stdout_record is not None:
            print(json.dumps(self._pending_stdout_record), flush=True)

    def deltint(self):
        if self.phase != "EMIT_ARRIVAL":
            self.passivate("PASSIVE")
            return

        # Clear pending emission artifacts
        self._pending_arrival_payload = None
        self._pending_stdout_record = None

        # Advance route index and schedule next arrival
        if not self.route_sequence:
            # Should not happen after initialize, but be defensive.
            self.passivate("PASSIVE")
            return

        self.i = (self.i + 1) % len(self.route_sequence)
        self.next_arrival_time = float(get_current_time()) + float(self.travel_interval_s)

        # Schedule next arrival after constant interval
        self.hold_in("EMIT_ARRIVAL", float(self.travel_interval_s))

    def exit(self):
        # No required termination output; runs indefinitely.
        pass