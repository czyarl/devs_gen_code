"""InputReader model for reading and parsing input request file."""

import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class InputReader(Atomic):
    """Read input request file and emit parsed events to AlarmSystem and ReportCollector."""

    def __init__(self, name: str, parent: Coupled | None, input_file: str):
        super().__init__(name)
        self.parent = parent
        self.input_file = input_file
        self.add_out_port(Port(dict, "input_event_out"))
        self.add_out_port(Port(dict, "input_fact_out"))
        self.schedule = []
        self.next_index = 0

    @staticmethod
    def _seconds(text: str) -> float:
        """Convert HH:MM:SS timestamp to seconds."""
        parts = text.split(":")
        if len(parts) != 3:
            raise ValueError("timestamp must have exactly 3 colon-separated fields")
        hours, minutes, seconds = (int(part) for part in parts)
        return hours * 3600.0 + minutes * 60.0 + seconds

    def _read_schedule(self) -> None:
        """Read and parse input file into schedule."""
        parsed = []
        try:
            with open(self.input_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:  # Skip blank lines
                        continue
                    fields = line.split()
                    if len(fields) != 3:
                        continue
                    try:
                        event_time = self._seconds(fields[0])
                        port = int(fields[1])
                        value = int(fields[2])
                        if port != 0:
                            continue
                        parsed.append((event_time, port, value))
                    except ValueError:
                        continue
        except FileNotFoundError:
            # If file not found, treat as empty schedule
            pass
        self.schedule = sorted(parsed, key=lambda item: item[0])

    def initialize(self):
        """Initialize by reading input file and scheduling first event."""
        self._read_schedule()
        self.next_index = 0
        if not self.schedule:
            self.passivate("DONE")
            return
        self.hold_in("EMIT", max(0.0, self.schedule[0][0]))

    def deltext(self, e):
        """Handle external input (none expected)."""
        self.continuef(e)

    def lambdaf(self):
        """Emit scheduled events."""
        if self.phase == "EMIT":
            event_time, port, value = self.schedule[self.next_index]
            # Emit to AlarmSystem
            self.output["input_event_out"].add({
                "input_time": event_time,
                "port": port,
                "value": value
            })
            # Emit to ReportCollector
            action = "arm" if value == 1 else "disarm"
            self.output["input_fact_out"].add({
                "time": event_time,
                "component": "input_reader",
                "message": f"{{{port} {value}}}"
            })

    def deltint(self):
        """Handle internal event (move to next scheduled event)."""
        self.next_index += 1
        if self.next_index >= len(self.schedule):
            self.passivate("DONE")
            return
        next_time = self.schedule[self.next_index][0]
        self.hold_in("EMIT", max(0.0, next_time - get_current_time()))

    def exit(self):
        """Clean up (none needed)."""
        pass