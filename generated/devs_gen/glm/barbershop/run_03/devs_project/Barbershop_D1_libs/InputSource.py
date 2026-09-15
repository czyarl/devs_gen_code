import sys

from xdevs.models import Atomic, Coupled, Port


class InputSource(Atomic):
    """Atomic model that reads a timestamped schedule from stdin and emits 'newcust' events."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(str, "cust_arrival"))
        self.schedule = []
        self.next_index = 0
        self.simulated_time = 0.0

    @staticmethod
    def _parse_timestamp(text: str) -> float:
        """Converts HH:MM:SS:mm string to absolute simulation time in seconds."""
        parts = text.split(":")
        if len(parts) != 4:
            raise ValueError(f"Invalid timestamp format: {text}. Expected HH:MM:SS:mm")
        
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        milliseconds = int(parts[3])
        
        return hours * 3600.0 + minutes * 60.0 + seconds + (milliseconds / 1000.0)

    def _read_schedule(self) -> None:
        """Reads all lines from stdin and parses them into the internal schedule."""
        parsed = []
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            
            # Format: 'HH:MM:SS:mm EventName'
            fields = line.split()
            if len(fields) < 2:
                continue
            
            timestamp_str = fields[0]
            event_name = fields[1]
            
            # The contract specifies EventName is expected to be 'newcust'.
            # We store the event_name to be emitted later.
            try:
                event_time = self._parse_timestamp(timestamp_str)
            except ValueError:
                continue
            
            parsed.append((event_time, event_name))
        
        # Sort by time to ensure sequential processing
        self.schedule = sorted(parsed, key=lambda item: item[0])

    def initialize(self):
        """Reads stdin and schedules the first event."""
        self._read_schedule()
        self.next_index = 0
        self.simulated_time = 0.0
        
        if not self.schedule:
            self.passivate("DONE")
            return
        
        # Schedule the first event relative to time 0.0
        first_event_time = self.schedule[0][0]
        self.hold_in("EMIT", max(0.0, first_event_time))

    def deltext(self, e):
        """This model does not process external inputs."""
        self.continuef(e)

    def lambdaf(self):
        """Outputs the 'newcust' string on the cust_arrival port."""
        if self.phase == "EMIT":
            # We don't need to check bounds here because deltint handles state transitions
            # and ensures we only reach lambdaf if a valid event is scheduled.
            _, event_name = self.schedule[self.next_index]
            self.output["cust_arrival"].add(event_name)

    def deltint(self):
        """Advances to the next event in the schedule or passivates if done."""
        self.simulated_time += self.sigma
        self.next_index += 1
        
        if self.next_index >= len(self.schedule):
            self.passivate("DONE")
            return
        
        next_event_time = self.schedule[self.next_index][0]
        delay = next_event_time - self.simulated_time
        self.hold_in("EMIT", max(0.0, delay))

    def exit(self):
        pass