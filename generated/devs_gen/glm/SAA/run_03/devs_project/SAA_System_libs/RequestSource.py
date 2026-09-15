import sys

from xdevs.models import Atomic, Coupled, Port


class RequestSource(Atomic):
    """Read input file and emit request and input_reader events at scheduled times."""

    def __init__(self, name: str, parent: Coupled | None, input_file: str):
        super().__init__(name)
        self.parent = parent
        self.input_file = input_file
        
        # Output ports
        self.add_out_port(Port(dict, "request_out"))
        self.add_out_port(Port(dict, "input_event_out"))
        
        # Internal state
        self.schedule = []  # List of (time, port, value)
        self.next_index = 0
        self.simulated_time = 0.0

    @staticmethod
    def _seconds(text: str) -> float:
        """Convert HH:MM:SS timestamp to seconds."""
        parts = text.split(":")
        if len(parts) != 3:
            raise ValueError("timestamp must have 3 colon-separated fields")
        hours, minutes, seconds = (int(part) for part in parts)
        return hours * 3600.0 + minutes * 60.0 + seconds

    def _read_schedule(self) -> None:
        """Parse the input file and populate the schedule."""
        parsed = []
        try:
            with open(self.input_file, 'r') as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        continue
                    
                    fields = line.split()
                    # Expected format: HH:MM:SS port value
                    if len(fields) < 3:
                        continue
                    
                    try:
                        event_time = self._seconds(fields[0])
                        port = int(fields[1])
                        value = int(fields[2])
                        parsed.append((event_time, port, value))
                    except ValueError:
                        # Skip lines with invalid numbers
                        continue
        except (FileNotFoundError, TypeError):
            # If file not found or path is invalid (e.g., None), remain passive (empty schedule)
            pass
            
        self.schedule = sorted(parsed, key=lambda item: item[0])

    def initialize(self):
        self._read_schedule()
        self.next_index = 0
        self.simulated_time = 0.0
        
        if not self.schedule:
            self.passivate("DONE")
            return
            
        # Schedule the first event
        first_time = self.schedule[0][0]
        self.hold_in("EMIT", max(0.0, first_time))

    def deltext(self, e: float):
        # This model has no input ports, so it should not receive external events.
        # However, the base class might call it. We just continue.
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "EMIT" and self.next_index < len(self.schedule):
            event_time, port, value = self.schedule[self.next_index]
            
            # Emit request payload
            self.output["request_out"].add({
                "input_time": event_time,
                "port": port,
                "value": value
            })
            
            # Emit input_reader event record
            # Message format is "{port value}"
            self.output["input_event_out"].add({
                "time": event_time,
                "component": "input_reader",
                "message": f"{{{port} {value}}}"
            })

    def deltint(self):
        self.simulated_time += self.sigma
        self.next_index += 1
        
        if self.next_index >= len(self.schedule):
            self.passivate("DONE")
            return
        
        # Schedule next event
        next_time = self.schedule[self.next_index][0]
        delay = max(0.0, next_time - self.simulated_time)
        self.hold_in("EMIT", delay)

    def exit(self):
        pass