"""InputReader model for reading timestamped input requests and emitting events."""

import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class InputReader(Atomic):
    """Reads input requests from a file and emits scheduled events."""

    def __init__(self, name: str, parent: Coupled | None, input_file: str):
        super().__init__(name)
        self.parent = parent
        self.input_file = input_file
        self.add_out_port(Port(dict, "request_out"))
        self.add_out_port(Port(dict, "input_fact_out"))
        self.schedule = []
        self.next_index = 0

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
        try:
            with open(self.input_file, 'r') as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue
                    fields = line.split()
                    if len(fields) < 3:
                        continue
                    try:
                        event_time = self._seconds(fields[0])
                        port = int(fields[1])
                        value = int(fields[2])
                    except (ValueError, IndexError):
                        continue
                    parsed.append((event_time, port, value))
        except FileNotFoundError:
            # If file is not found, treat as empty schedule
            pass
        self.schedule = sorted(parsed, key=lambda item: item[0])

    def initialize(self):
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
            # Emit request_out event
            self.output["request_out"].add({
                "input_time": event_time,
                "port": port,
                "value": value
            })
            # Emit input_fact_out event
            self.output["input_fact_out"].add({
                "time": event_time,
                "component": "input_reader",
                "message": f"{{0 {value}}}"
            })

    def deltint(self):
        self.next_index += 1
        if self.next_index >= len(self.schedule):
            self.passivate("DONE")
            return
        next_time = self.schedule[self.next_index][0]
        self.hold_in("EMIT", max(0.0, next_time - get_current_time()))

    def exit(self):
        pass