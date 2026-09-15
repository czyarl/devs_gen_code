"""CustomerSource model that reads customer arrival events from stdin and forwards them to ReceptionDesk."""

import sys
import json

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class CustomerSource(Atomic):
    """Reads customer arrival events from stdin, parses them into structured data, and sends each to the ReceptionDesk via the 'newcust' port."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "newcust"))
        self.schedule = []
        self.next_index = 0
        self.simulated_time = 0.0

    @staticmethod
    def _seconds(text: str) -> float:
        """Convert HH:MM:SS:mm timestamp string to float seconds."""
        parts = text.split(":")
        if len(parts) not in (3, 4):
            raise ValueError("timestamp must have 3 or 4 colon-separated fields")
        hours, minutes, seconds = (int(part) for part in parts[:3])
        fraction = float(f"0.{parts[3]}") if len(parts) == 4 else 0.0
        return hours * 3600.0 + minutes * 60.0 + seconds + fraction

    def _read_schedule(self) -> None:
        """Read all lines from stdin and parse into schedule."""
        parsed = []
        for raw_line in sys.stdin:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            fields = raw_line.split(None, 1)
            if len(fields) < 2:
                continue
            try:
                event_time = self._seconds(fields[0])
            except ValueError:
                continue
            event_name = fields[1]
            if event_name != "newcust":
                continue
            # Create a simple customer ID based on line number for this example
            # In a real system, this would be parsed from the line
            payload = {"customer_id": len(parsed) + 1}
            parsed.append((event_time, {
                "time": event_time,
                "event_type": "newcust",
                "payload": payload
            }))
        self.schedule = sorted(parsed, key=lambda item: item[0])

    def initialize(self):
        """Initialize by reading all input and scheduling first event."""
        self._read_schedule()
        self.next_index = 0
        self.simulated_time = 0.0
        if not self.schedule:
            self.passivate("DONE")
            return
        # Schedule initial event at t=0 as per protocol
        self.hold_in("EMIT", 0.0)

    def deltext(self, e):
        """Handle incoming external events (none expected)."""
        self.continuef(e)

    def lambdaf(self):
        """Emit the scheduled event and write to stdout."""
        if self.phase == "EMIT":
            event_time, payload = self.schedule[self.next_index]
            # Emit to DEVS port
            self.output["newcust"].add(payload)
            # Write to stdout as per external_io spec
            record = {
                "time": event_time,
                "type": "message",
                "model": "CustomerSource",
                "port": "newcust",
                "content": "newcust"
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        """Handle internal event (advance to next scheduled event)."""
        self.simulated_time += self.sigma
        self.next_index += 1
        if self.next_index >= len(self.schedule):
            self.passivate("DONE")
            return
        next_time = self.schedule[self.next_index][0]
        self.hold_in("EMIT", max(0.0, next_time - self.simulated_time))

    def exit(self):
        """Clean up on exit (none required for this model)."""
        pass