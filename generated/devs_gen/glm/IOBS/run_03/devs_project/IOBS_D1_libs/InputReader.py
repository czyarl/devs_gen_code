import json
import sys

from xdevs.models import Atomic, Coupled, Port


class InputReader(Atomic):
    """Reads timestamped requests from stdin, writes start/input records to stdout, and forwards requests to AAM."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "request_out"))
        
        # Internal state
        self.requests = []  # List of dicts: {'timestamp': float, 'valid': int, 'invalid': int}
        self.current_request_index = 0
        self.simulated_time = 0.0

    @staticmethod
    def _parse_timestamp(text: str) -> float:
        """Converts 'HH:MM:SS:mmm' string to float seconds."""
        parts = text.split(":")
        if len(parts) != 4:
            raise ValueError(f"Invalid timestamp format: {text}. Expected HH:MM:SS:mmm")
        
        hours, minutes, seconds = (int(part) for part in parts[:3])
        # parts[3] is milliseconds
        milliseconds = int(parts[3])
        
        return hours * 3600.0 + minutes * 60.0 + seconds + (milliseconds / 1000.0)

    def _read_and_parse_input(self) -> None:
        """Reads all lines from stdin and parses them into the internal queue."""
        parsed_requests = []
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            
            fields = line.split()
            # Format: HH:MM:SS:mmm valid invalid
            if len(fields) != 3:
                # Skip malformed lines silently or log to stderr if needed, 
                # but contract implies strict format.
                continue
            
            try:
                timestamp = self._parse_timestamp(fields[0])
                valid = int(fields[1])
                invalid = int(fields[2])
                
                parsed_requests.append({
                    "timestamp": timestamp,
                    "valid": valid,
                    "invalid": invalid
                })
            except ValueError:
                # Skip lines with parsing errors
                continue
        
        # Sort by timestamp to ensure chronological processing
        self.requests = sorted(parsed_requests, key=lambda x: x["timestamp"])

    def initialize(self):
        """Initializes the model, reads input, and schedules the first event."""
        self._read_and_parse_input()
        self.current_request_index = 0
        self.simulated_time = 0.0
        
        # Write 'start' event record to stdout at t=0
        record = {
            "time": 0.0,
            "model": self.name,
            "event": "start",
            "data": {}
        }
        print(json.dumps(record), flush=True)
        
        if not self.requests:
            self.passivate("PASSIVE")
        else:
            # Schedule first internal transition at the timestamp of the earliest request
            first_time = self.requests[0]["timestamp"]
            delay = max(0.0, first_time - self.simulated_time)
            self.hold_in("ACTIVE", delay)

    def deltext(self, e):
        """External transition: This model has no input ports, so this should not be called."""
        self.continuef(e)

    def lambdaf(self):
        """Output function: Sends the payload for the current request."""
        if self.phase == "ACTIVE" and self.current_request_index < len(self.requests):
            req = self.requests[self.current_request_index]
            
            # Prepare payload for DEVS port
            payload = {
                "timestamp": req["timestamp"],
                "valid": req["valid"],
                "invalid": req["invalid"]
            }
            self.output["request_out"].add(payload)

    def deltint(self):
        """Internal transition: Advances to the next request or passivates."""
        # Update simulated time based on the sigma that just elapsed
        self.simulated_time += self.sigma
        
        # Move to next request
        self.current_request_index += 1
        
        if self.current_request_index >= len(self.requests):
            # All requests processed, transition to passive state
            self.passivate("PASSIVE")
        else:
            # Schedule next internal transition
            next_req = self.requests[self.current_request_index]
            next_time = next_req["timestamp"]
            
            # Calculate delay from current simulated time to next request time
            delay = max(0.0, next_time - self.simulated_time)
            self.hold_in("ACTIVE", delay)

    def exit(self):
        """Cleanup: No specific resources to release."""
        pass