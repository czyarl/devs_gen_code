"""EventSource: Reads timestamped lines from stdin and emits newcust events."""

import sys
import json

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class EventSource(Atomic):
    """Reads timestamped lines from stdin and emits newcust events."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "newcust"))
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
        for raw_line in sys.stdin:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            fields = raw_line.split()
            # The timestamp plus at least one domain field are required.
            if len(fields) < 2:
                continue
            try:
                event_time = self._seconds(fields[0])
            except ValueError:
                continue
            if fields[1] != "newcust":
                continue
            parsed.append((event_time, fields[1]))
        self.schedule = sorted(parsed, key=lambda item: item[0])

    def initialize(self):
        self._read_schedule()
        self.next_index = 0
        if not self.schedule:
            self.passivate("DONE")
            return
        # Emit initial signal at t=0
        self.hold_in("EMIT", 0.0)

    def deltext(self, e):
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "EMIT":
            # Emit a state record for each newcust
            event_time, event_name = self.schedule[self.next_index]
            # Write JSONL state record to stdout
            record = {
                "time": event_time,
                "type": "state",
                "model": "reception",
                "field": "total customers num",
                "value": 1
            }
            print(json.dumps(record), flush=True)
            # Emit the newcust event on the output port
            self.output["newcust"].add({
                "time": event_time,
                "event": "newcust"
            })

    def deltint(self):
        self.next_index += 1
        if self.next_index >= len(self.schedule):
            self.passivate("DONE")
            return
        next_time = self.schedule[self.next_index][0]
        # Check if we should terminate based on real time
        current_sim_time = get_current_time()
        if current_sim_time >= 10.0:
            self.passivate("DONE")
            return
        self.hold_in("EMIT", max(0.0, next_time - get_current_time()))

    def exit(self):
        pass