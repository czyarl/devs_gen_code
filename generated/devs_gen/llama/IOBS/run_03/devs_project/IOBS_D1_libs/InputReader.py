import json
import sys
from datetime import datetime

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class InputReader(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "request_out"))

    def initialize(self):
        print(json.dumps({
            "time": get_current_time(),
            "model": "input_reader1",
            "event": "start",
            "data": {}
        }), flush=True)
        self.hold_in("wait", float('inf'))

    def deltext(self, e):
        self.continuef(e)

    def lambdaf(self):
        line = sys.stdin.readline().strip()
        if line:
            fields = line.split()
            if len(fields) == 3:
                try:
                    timestamp = self._parse_timestamp(fields[0])
                    valid = int(fields[1])
                    invalid = int(fields[2])
                    print(json.dumps({
                        "time": timestamp,
                        "model": "input_reader1",
                        "event": "input",
                        "data": {"valid": valid, "invalid": invalid}
                    }), flush=True)
                    self.hold_in("wait", max(0.0, timestamp - get_current_time()))
                except (IndexError, ValueError):
                    self.continuef(0)

    def deltint(self):
        pass

    def exit(self):
        pass

    @staticmethod
    def _parse_timestamp(timestamp_str: str) -> float:
        try:
            dt = datetime.strptime(timestamp_str, "%H:%M:%S:%f")
            return (dt.hour * 3600 + dt.minute * 60 + dt.second + dt.microsecond / 1000000)
        except ValueError:
            return 0.0