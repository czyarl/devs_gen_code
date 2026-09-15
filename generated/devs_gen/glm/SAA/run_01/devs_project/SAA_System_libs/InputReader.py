"""Atomic DEVS model: InputReader."""

import sys

from xdevs.models import Atomic, Coupled, Port


class InputReader(Atomic):
    """Reads operation requests from a file and emits them at scheduled times."""

    def __init__(self, name: str, parent: Coupled | None, input_file: str):
        super().__init__(name)
        self.parent = parent
        self.input_file = input_file

        # Output ports
        self.add_out_port(Port(dict, "request_out"))
        self.add_out_port(Port(dict, "input_event_out"))

        # Internal state
        self.schedule = []
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
        """Read and parse the input file."""
        parsed = []
        try:
            with open(self.input_file, 'r') as f:
                for raw_line in f:
                    line = raw_line.strip()
                    if not line:
                        # Ignore blank lines
                        continue
                    
                    fields = line.split()
                    # Format: 'HH:MM:SS port value'
                    if len(fields) != 3:
                        # Malformed line, skip or raise error based on strictness.
                        # Contract implies strict format, skipping is safer for robustness
                        # or we could raise. Given "Parse all non-empty lines formatted as...",
                        # we assume valid input or skip invalid to avoid crash.
                        continue

                    try:
                        timestamp_str = fields[0]
                        port = int(fields[1])
                        value = int(fields[2])
                        
                        event_time = self._seconds(timestamp_str)
                        
                        # Store as tuple: (time, port, value)
                        parsed.append((event_time, port, value))
                    except ValueError:
                        # Skip lines with parsing errors
                        continue
        except FileNotFoundError:
            # If file not found, schedule remains empty, model passivates.
            print(f"Input file not found: {self.input_file}", file=sys.stderr)
            return

        # Sort by simulation time
        self.schedule = sorted(parsed, key=lambda item: item[0])

    def initialize(self):
        self._read_schedule()
        self.next_index = 0
        self.simulated_time = 0.0
        
        if not self.schedule:
            self.passivate("PASSIVE")
            return

        # Schedule the first internal transition for the earliest timestamp
        first_event_time = self.schedule[0][0]
        self.hold_in("ACTIVE", max(0.0, first_event_time))

    def deltext(self, e: float):
        # This model has no input ports, so deltext is irrelevant for logic,
        # but must be implemented to satisfy Atomic interface if called by framework.
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "ACTIVE":
            # Retrieve current event data
            event_time, port, value = self.schedule[self.next_index]

            # Emit business request via request_out
            # Format: {'input_time': float, 'port': int, 'value': int}
            self.output["request_out"].add({
                'input_time': event_time,
                'port': port,
                'value': value
            })

            # Emit event record via input_event_out
            # Format: {'time': float, 'component': 'input_reader', 'message': str}
            # Message format is '{port value}'
            message = f"{{{port} {value}}}"
            self.output["input_event_out"].add({
                'time': event_time,
                'component': 'input_reader',
                'message': message
            })

    def deltint(self):
        # Update simulated time tracker
        self.simulated_time += self.sigma
        
        # Move to next event
        self.next_index += 1

        if self.next_index >= len(self.schedule):
            # Become passive after the last event
            self.passivate("PASSIVE")
        else:
            # Schedule next internal transition
            next_event_time = self.schedule[self.next_index][0]
            delay = next_event_time - self.simulated_time
            self.hold_in("ACTIVE", max(0.0, delay))

    def exit(self):
        # No specific cleanup required
        pass