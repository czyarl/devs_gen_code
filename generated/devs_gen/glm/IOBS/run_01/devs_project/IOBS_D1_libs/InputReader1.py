import sys
import json

from xdevs.models import Atomic, Coupled, Port


class InputReader1(Atomic):
    """Reads timestamped login requests from standard input during initialization."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "request_out"))
        
        self.schedule = []
        self.next_index = 0
        self.simulated_time = 0.0

    @staticmethod
    def _parse_timestamp(text: str) -> float:
        """Parses HH:MM:SS:mmm into simulation seconds."""
        parts = text.split(":")
        if len(parts) != 4:
            raise ValueError("Timestamp must have 4 colon-separated fields: HH:MM:SS:mmm")
        
        hours, minutes, seconds = (int(part) for part in parts[:3])
        milliseconds = int(parts[3])
        
        return hours * 3600.0 + minutes * 60.0 + seconds + (milliseconds / 1000.0)

    def _read_schedule(self) -> None:
        """Reads from sys.stdin and parses lines into a sorted schedule."""
        parsed = []
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            
            fields = line.split()
            if len(fields) != 3:
                # Malformed line based on spec "HH:MM:SS:mmm valid invalid"
                continue
            
            try:
                timestamp = self._parse_timestamp(fields[0])
                valid = int(fields[1])
                invalid = int(fields[2])
            except ValueError:
                continue
            
            parsed.append({
                "time": timestamp,
                "valid": valid,
                "invalid": invalid
            })
        
        # Sort by timestamp to ensure nondecreasing order
        self.schedule = sorted(parsed, key=lambda item: item["time"])

    def initialize(self):
        """Initializes the model, reads stdin, and schedules the first event."""
        self._read_schedule()
        self.next_index = 0
        self.simulated_time = 0.0
        
        # Emit 'start' event at absolute time 0.0
        record = {
            "time": 0.0,
            "model": "input_reader1",
            "event": "start",
            "data": {}
        }
        print(json.dumps(record), flush=True)
        
        if not self.schedule:
            self.passivate("PASSIVE")
            return
        
        # Schedule the first input event
        first_event_time = self.schedule[0]["time"]
        delay = max(0.0, first_event_time - self.simulated_time)
        self.hold_in("ACTIVE", delay)

    def deltext(self, e: float):
        """This model has no input ports, so this method is not strictly used but required by API."""
        self.continuef(e)

    def lambdaf(self):
        """Emits the payload for the current scheduled request."""
        if self.phase == "ACTIVE" and self.next_index < len(self.schedule):
            current_event = self.schedule[self.next_index]
            
            # Prepare payload for DEVS output port
            payload = {
                "valid": current_event["valid"],
                "invalid": current_event["invalid"]
            }
            self.output["request_out"].add(payload)
            
            # Emit 'input' event to stdout
            record = {
                "time": current_event["time"],
                "model": "input_reader1",
                "event": "input",
                "data": payload
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        """Advances to the next scheduled request or passivates."""
        self.simulated_time += self.sigma
        self.next_index += 1
        
        if self.next_index >= len(self.schedule):
            self.passivate("PASSIVE")
        else:
            next_event = self.schedule[self.next_index]
            delay = max(0.0, next_event["time"] - self.simulated_time)
            self.hold_in("ACTIVE", delay)

    def exit(self):
        """Cleanup method."""
        pass