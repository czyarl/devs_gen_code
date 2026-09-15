"""InputReader: Read input file and emit request and fact events."""

import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class InputReader(Atomic):
    """Read input file and emit request and fact events."""

    def __init__(self, name: str, parent: Coupled | None, input_path: str):
        super().__init__(name)
        self.parent = parent
        self.input_path = input_path
        self.add_out_port(Port(dict, "request_out"))
        self.add_out_port(Port(dict, "input_fact_out"))
        self.schedule = []
        self.next_index = 0

    @staticmethod
    def _seconds(text: str) -> float:
        """Convert HH:MM:SS format to seconds."""
        parts = text.split(":")
        if len(parts) != 3:
            raise ValueError("timestamp must have exactly 3 colon-separated fields")
        hours, minutes, seconds = (int(part) for part in parts)
        return hours * 3600.0 + minutes * 60.0 + seconds

    def _read_schedule(self) -> None:
        """Read and parse input file."""
        parsed = []
        with open(self.input_path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                fields = line.split()
                if len(fields) != 3:
                    continue
                try:
                    event_time = self._seconds(fields[0])
                except ValueError:
                    continue
                port = int(fields[1])
                value = int(fields[2])
                if port != 0:
                    continue
                parsed.append((event_time, port, value))
        self.schedule = sorted(parsed, key=lambda item: item[0])

    def initialize(self):
        if self.input_path is None:
            self.passivate("DONE")
            return
        self._read_schedule()
        self.next_index = 0
        if not self.schedule:
            self.passivate("DONE")
            return
        self.hold_in("EMIT", max(0.0, self.schedule[0][0]))

    def deltext(self, e):
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "EMIT":
            event_time, port, value = self.schedule[self.next_index]
            # Emit business request
            request = {
                "input_time": event_time,
                "port": port,
                "value": value
            }
            self.output["request_out"].add(request)
            # Emit input fact
            message = f"{{0 {value}}}"
            input_fact = {
                "time": event_time,
                "component": "input_reader",
                "message": message
            }
            self.output["input_fact_out"].add(input_fact)

    def deltint(self):
        self.next_index += 1
        if self.next_index >= len(self.schedule):
            self.passivate("DONE")
            return
        next_time = self.schedule[self.next_index][0]
        self.hold_in("EMIT", max(0.0, next_time - get_current_time()))

    def exit(self):
        pass