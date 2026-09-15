"""InputReader1: Reads timestamped login requests from stdin and schedules them."""

import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class InputReader1(Atomic):
    """Reads timestamped login requests from stdin and schedules them."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "input_out"))
        self.schedule = []
        self.next_index = 0
        self.simulated_time = 0.0

    @staticmethod
    def _seconds(text: str) -> float:
        parts = text.split(":")
        if len(parts) != 4:
            raise ValueError("timestamp must have 4 colon-separated fields")
        hours, minutes, seconds, milliseconds = (int(part) for part in parts)
        return hours * 3600.0 + minutes * 60.0 + seconds + milliseconds / 1000.0

    def _read_schedule(self) -> None:
        parsed = []
        for raw_line in sys.stdin:
            fields = raw_line.split()
            if len(fields) < 3:
                continue
            try:
                event_time = self._seconds(fields[0])
            except ValueError:
                continue
            valid = int(fields[1])
            invalid = int(fields[2])
            parsed.append((event_time, valid, invalid))
        self.schedule = sorted(parsed, key=lambda item: item[0])

    def initialize(self):
        self._read_schedule()
        self.next_index = 0
        self.simulated_time = 0.0
        # Emit start event at t=0
        start_time = 0.0
        self.output["input_out"].add({
            "valid": 1,
            "invalid": 0
        })
        # Schedule first event if any
        if not self.schedule:
            self.passivate("DONE")
            return
        self.hold_in("EMIT", max(0.0, self.schedule[0][0]))

    def deltext(self, e):
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "EMIT":
            event_time, valid, invalid = self.schedule[self.next_index]
            self.output["input_out"].add({
                "valid": valid,
                "invalid": invalid
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