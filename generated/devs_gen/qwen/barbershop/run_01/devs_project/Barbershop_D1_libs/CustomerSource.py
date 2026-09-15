import sys
import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class CustomerSource(Atomic):
    """Reads customer arrival events from stdin and emits them to ReceptionDesk."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(str, "cust"))
        self.events = []
        self.current_time = 0.0
        self.total_customers = 0

    def initialize(self):
        # Read all stdin lines
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                time_str, event_name = line.split(" ", 1)
                if event_name != "newcust":
                    continue
                # Parse timestamp HH:MM:SS:mm
                h, m, s, ms = time_str.split(":")
                absolute_time = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 100.0
                self.events.append((absolute_time, event_name))
            except (ValueError, IndexError):
                continue

        # Sort events by time
        self.events.sort(key=lambda x: x[0])

        # Emit state change for each event
        for time_val, event in self.events:
            self.current_time = time_val
            self.total_customers += 1
            record = {
                "time": time_val,
                "type": "state",
                "model": "reception",
                "field": "total customers num",
                "value": str(self.total_customers)
            }
            print(json.dumps(record), flush=True)

        # Schedule the first event if any
        if self.events:
            self.hold_in("OUTPUT_READY", 0.0)
        else:
            self.passivate("DONE")

    def deltext(self, e):
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "OUTPUT_READY":
            # Send all events at their respective times
            if self.events:
                time_val, event_name = self.events.pop(0)
                self.current_time = time_val
                # Emit message
                record = {
                    "time": time_val,
                    "type": "message",
                    "model": "reception",
                    "port": "cust",
                    "content": event_name
                }
                print(json.dumps(record), flush=True)
                # Send to output port
                self.output["cust"].add(event_name)
                # Schedule next event if available
                if self.events:
                    self.hold_in("OUTPUT_READY", 0.0)
                else:
                    self.passivate("DONE")

    def deltint(self):
        pass

    def exit(self):
        pass