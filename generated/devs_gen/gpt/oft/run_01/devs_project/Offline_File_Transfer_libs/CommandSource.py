import sys

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class CommandSource(Atomic):
    """
    Atomic DEVS model that consumes stdin once at initialization, parses timestamped
    'control'/'request' commands, and emits them at their absolute simulation times (ms).
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_out_port(Port(dict, "control_out"))
        self.add_out_port(Port(dict, "request_out"))

        # Schedule entries: (timestamp_ms: float, kind: str, payload: dict)
        self._schedule: list[tuple[float, str, dict]] = []
        self._next_index: int = 0

        # Current simulated time tracked by internal transitions (ms)
        self._sim_time_ms: float = 0.0

        # Due set prepared for the next emission time (may include mixed kinds)
        self._due_time_ms: float | None = None
        self._due_controls: list[dict] = []
        self._due_requests: list[dict] = []

    @staticmethod
    def _parse_time_to_ms(text: str) -> float:
        parts = text.split(":")
        if len(parts) not in (3, 4):
            raise ValueError("time must be HH:MM:SS or HH:MM:SS:mmm")
        hh = int(parts[0])
        mm = int(parts[1])
        ss = int(parts[2])
        mmm = int(parts[3]) if len(parts) == 4 else 0
        if hh < 0 or mm < 0 or ss < 0 or mmm < 0:
            raise ValueError("negative time fields not allowed")
        return float(((hh * 3600 + mm * 60 + ss) * 1000) + mmm)

    @staticmethod
    def _parse_line_to_command(line: str) -> tuple[float, str, dict] | None:
        fields = line.split()
        if len(fields) != 3:
            return None

        try:
            timestamp_ms = CommandSource._parse_time_to_ms(fields[0])
        except Exception:
            return None

        cmd_type = fields[1]
        try:
            value_int = int(fields[2])
        except Exception:
            return None

        if timestamp_ms < 0:
            return None

        if cmd_type == "control":
            return (timestamp_ms, "control", {"added": int(value_int)})

        if cmd_type == "request":
            if value_int not in (0, 1):
                return None
            return (timestamp_ms, "request", {"allowed": bool(value_int)})

        return None

    def _read_and_build_schedule(self) -> None:
        parsed: list[tuple[float, str, dict]] = []
        for raw_line in sys.stdin:
            if not raw_line.strip():
                continue
            cmd = self._parse_line_to_command(raw_line)
            if cmd is None:
                continue
            parsed.append(cmd)

        # Sort by timestamp; duplicates preserved; stable ordering for identical timestamps.
        parsed.sort(key=lambda x: x[0])
        self._schedule = parsed
        self._next_index = 0

    def _prepare_due_set(self) -> None:
        self._due_controls = []
        self._due_requests = []
        self._due_time_ms = None

        if self._next_index >= len(self._schedule):
            return

        due_time = self._schedule[self._next_index][0]

        # Guard: never emit commands in the past relative to our tracked sim time.
        if due_time < self._sim_time_ms:
            # Skip all commands that are already in the past (invalid/ignored).
            while self._next_index < len(self._schedule) and self._schedule[self._next_index][0] < self._sim_time_ms:
                self._next_index += 1
            if self._next_index >= len(self._schedule):
                return
            due_time = self._schedule[self._next_index][0]
            if due_time < self._sim_time_ms:
                return

        self._due_time_ms = due_time
        while self._next_index < len(self._schedule) and self._schedule[self._next_index][0] == due_time:
            _, kind, payload = self._schedule[self._next_index]
            if kind == "control":
                self._due_controls.append(payload)
            else:
                self._due_requests.append(payload)
            self._next_index += 1

    def initialize(self):
        self._read_and_build_schedule()
        self._sim_time_ms = 0.0

        if not self._schedule:
            self.passivate("DONE")
            return

        # Prepare first due set and schedule the first emission.
        self._next_index = 0
        self._prepare_due_set()
        if self._due_time_ms is None:
            self.passivate("DONE")
            return

        # At t=0, schedule immediate internal event if due_time_ms == 0.
        delay = max(0.0, self._due_time_ms - self._sim_time_ms)
        self.hold_in("EMIT", delay)

    def deltext(self, e: float):
        # No input ports; just advance time if active.
        self.continuef(e)

    def lambdaf(self):
        if self.phase != "EMIT":
            return

        # Emit all due commands at this time; each command produces exactly one message.
        for payload in self._due_controls:
            self.output["control_out"].add(payload)
        for payload in self._due_requests:
            self.output["request_out"].add(payload)

    def deltint(self):
        # Advance simulated time by sigma (ms)
        self._sim_time_ms += float(self.sigma)

        # Clear due set that was just emitted
        self._due_controls = []
        self._due_requests = []
        self._due_time_ms = None

        # Prepare next due set and schedule next emission
        if self._next_index >= len(self._schedule):
            self.passivate("DONE")
            return

        self._prepare_due_set()
        if self._due_time_ms is None:
            self.passivate("DONE")
            return

        # Ensure we never schedule negative delay; also ignore any "past" commands already skipped.
        delay = self._due_time_ms - self._sim_time_ms
        if delay < 0.0:
            # As a safety net, treat as invalid/past and move on.
            while self._next_index < len(self._schedule) and self._schedule[self._next_index][0] < self._sim_time_ms:
                self._next_index += 1
            self._prepare_due_set()
            if self._due_time_ms is None:
                self.passivate("DONE")
                return
            delay = max(0.0, self._due_time_ms - self._sim_time_ms)

        self.hold_in("EMIT", float(delay))

    def exit(self):
        # No external outputs required; must not write stdout.
        _ = get_current_time()  # available if needed; kept to satisfy utility availability without side effects.
        return