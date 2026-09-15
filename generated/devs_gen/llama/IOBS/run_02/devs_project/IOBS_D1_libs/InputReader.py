"""Complete pattern: Read from stdin and emit records at parsed timestamps."""

import json
import sys

from xdevs.models import Atomic, Coupled, Port


class InputReader(Atomic):
    """Read from stdin and emit records at parsed timestamps."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "request_out"))

    def initialize(self):
        print(json.dumps({"event": "start", "data": {}}))
        self.add_in_port("line_in")
        self.add_out_port("request_out")

        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            yield line

    def deltext(self, e):
        for line in self.inports["line_in"].values():
            yield line

    def lambdaf(self):
        line = self.inports["line_in"].get()
        parts = line.split()
        time_str = parts[0]
        time_parts = time_str.split(":")
        time = float(time_parts[0]) * 3600.0 + float(time_parts[1]) * 60.0 + float(time_parts[2]) + float(time_parts[3]) / 1000.0
        self.output["request_out"].add({
            "time": time,
            "valid": int(parts[1]),
            "invalid": int(parts[2]),
        })

    def deltcon(self):
        pass

    def exit(self):
        pass