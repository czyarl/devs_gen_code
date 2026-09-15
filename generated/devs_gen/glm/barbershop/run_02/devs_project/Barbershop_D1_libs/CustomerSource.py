import sys

from xdevs.models import Atomic, Coupled, Port


class CustomerSource(Atomic):
    """Reads the initial schedule from stdin, parses arrival times, and emits 'newcust' events to the Reception desk at the correct simulation times."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(str, "out"))
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
            fields = raw_line.split()
            if len(fields) < 2:
                continue
            try:
                event_time = self._seconds(fields[0])
            except ValueError:
                continue
            # The contract specifies format: HH:MM:SS:mm newcust
            # fields[0] is time, fields[1] is event name.
            # We only care about 'newcust' events based on requirements, but the source
            # essentially just parses what is there.
            parsed.append((event_time, fields[1]))
        self.schedule = sorted(parsed, key=lambda item: item[0])

    def initialize(self):
        self._read_schedule()
        self.next_index = 0
        self.simulated_time = 0.0
        if not self.schedule:
            self.passivate("DONE")
            return
        # Schedule the first event. The time is absolute simulation time.
        # Since simulation starts at 0.0, the delay is simply the event time.
        self.hold_in("EMIT", max(0.0, self.schedule[0][0]))

    def deltext(self, e):
        # This model has no input ports, so deltext should not be called with data.
        # However, if called (e.g. by root), we just continue.
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "EMIT":
            # Emit the event payload
            _, event_name = self.schedule[self.next_index]
            self.output["out"].add(event_name)

    def deltint(self):
        # Update internal simulation time tracker
        self.simulated_time += self.sigma
        self.next_index += 1
        
        if self.next_index >= len(self.schedule):
            self.passivate("DONE")
            return
        
        # Calculate delay to next event
        next_event_time = self.schedule[self.next_index][0]
        delay = max(0.0, next_event_time - self.simulated_time)
        self.hold_in("EMIT", delay)

    def exit(self):
        pass