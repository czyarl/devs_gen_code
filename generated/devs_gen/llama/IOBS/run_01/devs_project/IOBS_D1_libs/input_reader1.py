"""Complete pattern: Read lines from stdin, parse timestamped requests, and emit events."""

import json
import sys
from datetime import datetime

from xdevs.models import Atomic, Coupled, Port


class input_reader1(Atomic):
    """Read lines from stdin, parse timestamped requests, and emit events."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "AAM1_in"))

    def _parse_timestamp(self, text: str) -> float:
        parts = text.split(":")
        if len(parts) != 3:
            raise ValueError("timestamp must have 3 colon-separated fields")
        hours, minutes, seconds = (int(part) for part in parts[:3])
        fraction = float(f"0.{parts[3]}") if len(parts) == 4 else 0.0
        return (
            hours * 3600.0 + minutes * 60.0 + seconds + fraction
        )

    def initialize(self):
        print(json.dumps({
            "time": 0.0,
            "model": "input_reader1",
            "event": "start",
            "data": {}
        }), flush=True)
        self.hold_in("WAIT_INPUT", 0.0)

    def deltext(self, e: float):
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "WAIT_INPUT":
            line = sys.stdin.readline().strip()
            if not line:
                self.passivate("DONE")
                return
            try:
                timestamp = self._parse_timestamp(line[:15])
                valid, invalid = (int(x) for x in line[16:].split())
                self.output["AAM1_in"].add({
                    'valid': valid,
                    'invalid': invalid
                })
                print(json.dumps({
                    "time": timestamp,
                    "model": "input_reader1",
                    "event": "input",
                    "data": {"valid": valid, "invalid": invalid}
                }), flush=True)
            except Exception as ex:
                print(f"ERROR: {ex}", file=sys.stderr, flush=True)

    def deltint(self):
        pass

    def exit(self):
        pass