import sys

from xdevs.models import Atomic, Coupled, Port


class InputHandler(Atomic):
    """
    Reads and parses 'control' and 'request' commands from stdin.
    At the parsed simulation time, emits the command payload to the
    Sender or ServerSender via output ports.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Output ports defined in the contract
        self.add_out_port(Port(int, "control_out"))
        self.add_out_port(Port(int, "request_out"))

        # Internal state
        self.schedule = []  # List of (time_ms, type, value)
        self.next_index = 0
        self.simulated_time = 0.0

        # Helper to hold the payload for the current event
        self.current_payload = None

    @staticmethod
    def _parse_timestamp(text: str) -> float:
        """
        Parses HH:MM:SS:mmm or HH:MM:SS into milliseconds.
        """
        parts = text.split(":")
        if len(parts) not in (3, 4):
            raise ValueError(f"Invalid timestamp format: {text}")

        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        
        # Handle milliseconds if present
        if len(parts) == 4:
            # parts[3] is mmm
            ms = int(parts[3])
        else:
            ms = 0

        return (hours * 3600.0 + minutes * 60.0 + seconds) * 1000.0 + ms

    def _read_schedule(self) -> None:
        """
        Reads stdin line-by-line and parses commands.
        Format: 'HH:MM:SS:mmm type value' or 'HH:MM:SS type value'
        """
        parsed = []
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue

            fields = line.split()
            # Expected fields: timestamp, type, value
            if len(fields) < 3:
                # Invalid line format, skip
                continue

            try:
                time_ms = self._parse_timestamp(fields[0])
            except ValueError:
                # Skip lines with invalid timestamps
                continue

            cmd_type = fields[1]
            cmd_value_str = fields[2]

            # Validate type and value
            if cmd_type == "control":
                try:
                    val = int(cmd_value_str)
                    # control expects an integer N
                    parsed.append((time_ms, "control", val))
                except ValueError:
                    continue
            elif cmd_type == "request":
                try:
                    val = int(cmd_value_str)
                    # request expects 0 or 1
                    if val in (0, 1):
                        parsed.append((time_ms, "request", val))
                except ValueError:
                    continue
            else:
                # Unknown command type
                continue

        # Sort by time to ensure correct order
        self.schedule = sorted(parsed, key=lambda item: item[0])

    def initialize(self):
        self._read_schedule()
        self.next_index = 0
        self.simulated_time = 0.0
        self.current_payload = None

        if not self.schedule:
            self.passivate("DONE")
            return

        # Schedule the first event
        first_time = self.schedule[0][0]
        self.hold_in("EMIT", max(0.0, first_time))

    def deltext(self, e):
        # This model has no input ports, so deltext is not expected to receive anything.
        # However, standard Atomic models must handle it.
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "EMIT":
            # Emit the prepared payload
            if self.current_payload:
                port_name, value = self.current_payload
                self.output[port_name].add(value)

    def deltint(self):
        # Advance simulation time
        self.simulated_time += self.sigma

        # Move to next event
        self.next_index += 1

        if self.next_index >= len(self.schedule):
            self.passivate("DONE")
            self.current_payload = None
            return

        # Prepare next event
        next_time, cmd_type, cmd_value = self.schedule[self.next_index]
        self.current_payload = None

        if cmd_type == "control":
            self.current_payload = ("control_out", cmd_value)
        elif cmd_type == "request":
            self.current_payload = ("request_out", cmd_value)

        # Calculate delay
        delay = max(0.0, next_time - self.simulated_time)
        self.hold_in("EMIT", delay)

    def exit(self):
        pass