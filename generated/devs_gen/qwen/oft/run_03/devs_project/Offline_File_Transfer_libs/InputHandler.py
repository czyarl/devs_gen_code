"""InputHandler: Reads stdin line-by-line for timestamped control and request commands."""

import sys
import json

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class InputHandler(Atomic):
    """Parses stdin commands and forwards them to Sender and Server components."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "control_cmd"))
        self.add_out_port(Port(dict, "download_valve_change"))
        self.schedule = []
        self.next_index = 0
        self.simulated_time = 0.0

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
            if len(fields) < 3:
                continue
            try:
                event_time = self._seconds(fields[0])
            except ValueError:
                continue
            parsed.append((event_time, fields[1], fields[2]))
        self.schedule = sorted(parsed, key=lambda item: item[0])

    def initialize(self):
        self._read_schedule()
        self.next_index = 0
        self.simulated_time = 0.0
        if not self.schedule:
            self.passivate("DONE")
            return
        self.hold_in("EMIT", max(0.0, self.schedule[0][0]))

    def deltext(self, e):
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "EMIT":
            event_time, cmd_type, value = self.schedule[self.next_index]
            # Emit JSONL record to stdout
            record = {
                "timestamp_ms": event_time * 1000.0,
                "model": "input_handler",
                "type": "command_received",
                "val": {
                    "type": cmd_type,
                    "value": value
                }
            }
            print(json.dumps(record), flush=True)
            # Emit DEVS port event
            if cmd_type == "control":
                added = int(value)
                # For the purpose of this model, we do not track total_remaining
                # as it's not required by the locked contract
                self.output["control_cmd"].add({
                    "added": added,
                    "total_remaining": added  # Placeholder; actual logic not needed here
                })
            elif cmd_type == "request":
                allowed = bool(int(value))
                self.output["download_valve_change"].add({
                    "allowed": allowed
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