"""Complete pattern: schedule control commands from stdin."""

import json
import sys

from xdevs.models import Atomic, Coupled, Port


class InputHandler(Atomic):
    """Parse text records once and emit one payload at each recorded time."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "control_cmd"))

    def initialize(self):
        self.input_schedule = []
        self.next_index = 0
        self.simulated_time = 0.0

        # Read from stdin
        for line in sys.stdin:
            try:
                record = json.loads(line)
                if record["type"] == "control":
                    self.input_schedule.append((record["timestamp_ms"] / 1000.0, record))
            except Exception as e:
                print(f"Error parsing line: {line.strip()}", file=sys.stderr)

        if not self.input_schedule:
            self.passivate("DONE")
            return
        self.hold_in("EMIT", max(0.0, self.input_schedule[0][0]))

    def deltext(self, e):
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "EMIT":
            event_time, record = self.input_schedule[self.next_index]
            self.output["control_cmd"].add({
                "added": record["val"]["added"],
                "total_remaining": record["val"]["total_remaining"],
            })

    def deltint(self):
        self.simulated_time += self.sigma
        self.next_index += 1
        if self.next_index >= len(self.input_schedule):
            self.passivate("DONE")
            return
        next_time = self.input_schedule[self.next_index][0]
        self.hold_in("EMIT", max(0.0, next_time - self.simulated_time))

    def exit(self):
        pass