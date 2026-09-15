"""InputHandler: Reads stdin line-by-line and parses commands to emit control and request events."""

import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class InputHandler(Atomic):
    """Reads input from stdin and emits control and request events."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "control_out"))
        self.add_out_port(Port(dict, "download_valve_out"))
        self.schedule = []
        self.next_index = 0
        self.simulated_time = 0.0

    @staticmethod
    def _seconds(text: str) -> float:
        parts = text.split(":")
        if len(parts) not in (3, 4):
            raise ValueError("timestamp must have 3 or 4 colon-separated fields")
        hours, minutes, seconds = (int(part) for part in parts[:3])
        fraction = float(f"0.{parts[3]}") if len(parts) == 4 else 0.0
        return hours * 3600.0 + minutes * 60.0 + seconds + fraction

    def _read_schedule(self) -> None:
        parsed = []
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            fields = line.split()
            if len(fields) < 3:
                continue
            try:
                event_time = self._seconds(fields[0])
            except ValueError:
                continue
            event_type = fields[1]
            value = fields[2]
            if event_type not in ("control", "request"):
                continue
            parsed.append((event_time, event_type, value))
        self.schedule = sorted(parsed, key=lambda item: item[0])

    def initialize(self):
        self._read_schedule()
        self.next_index = 0
        self.simulated_time = 0.0
        if not self.schedule:
            self.passivate("DONE")
            return
        self.hold_in("EMIT", max(0.0, self.schedule[0][0]))

    def deltext(self, e):
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "EMIT":
            event_time, event_type, value = self.schedule[self.next_index]
            if event_type == "control":
                value_int = int(value)
                self.output["control_out"].add({
                    "added": value_int,
                    "total_remaining": value_int
                })
            elif event_type == "request":
                value_int = int(value)
                self.output["download_valve_out"].add({
                    "allowed": bool(value_int)
                })

    def deltint(self):
        self.simulated_time += self.sigma
        self.next_index += 1
        if self.next_index >= len(self.schedule):
            self.passivate("DONE")
            return
        next_time = self.schedule[self.next_index][0]
        self.hold_in("EMIT", max(0.0, next_time - self.simulated_time))

    def exit(self):
        pass