"""InputReader1: Reads timestamped requests from stdin, parses each line into a structured request, and schedules the request to be emitted to AAM1 at the specified time."""

import sys
import json

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class InputReader1(Atomic):
    """Reads timestamped requests from stdin, parses each line into a structured request, and schedules the request to be emitted to AAM1 at the specified time."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "input"))
        self.schedule = []
        self.next_index = 0
        self.simulated_time = 0.0

    @staticmethod
    def _seconds(text: str) -> float:
        parts = text.split(":")
        if len(parts) != 4:
            raise ValueError("timestamp must have 4 colon-separated fields: HH:MM:SS:mmm")
        hours, minutes, seconds, milliseconds = (int(part) for part in parts)
        return hours * 3600.0 + minutes * 60.0 + seconds + milliseconds / 1000.0

    def _read_schedule(self) -> None:
        parsed = []
        for raw_line in sys.stdin:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            fields = raw_line.split()
            if len(fields) != 3:
                continue
            try:
                event_time = self._seconds(fields[0])
            except ValueError:
                continue
            valid = int(fields[1])
            invalid = int(fields[2])
            if valid != 1 or invalid not in (0, 1):
                continue
            parsed.append((event_time, {"valid": valid, "invalid": invalid}))
        self.schedule = sorted(parsed, key=lambda item: item[0])

    def initialize(self):
        # Emit start event at t=0
        start_record = {
            "time": 0.0,
            "model": "input_reader1",
            "event": "start",
            "data": {}
        }
        print(json.dumps(start_record), flush=True)

        # Read and parse all input
        self._read_schedule()
        self.next_index = 0
        self.simulated_time = 0.0

        if not self.schedule:
            self.passivate("DONE")
            return

        # Schedule first event
        self.hold_in("EMIT", max(0.0, self.schedule[0][0]))

    def deltext(self, e):
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "EMIT":
            event_time, data = self.schedule[self.next_index]
            # Emit to stdout
            input_record = {
                "time": event_time,
                "model": "input_reader1",
                "event": "input",
                "data": data
            }
            print(json.dumps(input_record), flush=True)
            # Emit to DEVS output port
            self.output["input"].add(data)

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