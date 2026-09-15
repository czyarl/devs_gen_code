"""Atomic DEVS model InputSource for reading timestamped requests."""

from xdevs.models import Atomic, Coupled, Port


class InputSource(Atomic):
    """Reads a file of timestamped requests and emits them at the correct simulation times."""

    def __init__(self, name: str, parent: Coupled | None, input_path: str):
        super().__init__(name)
        self.parent = parent
        self.input_path = input_path

        # Output ports
        self.add_out_port(Port(dict, "request_out"))
        self.add_out_port(Port(dict, "input_fact_out"))

        # Internal state
        self.requests: list[dict] = []
        self.next_index: int = 0
        self.simulated_time: float = 0.0

    def _parse_timestamp(self, time_str: str) -> float:
        """Convert HH:MM:SS string to seconds."""
        parts = time_str.split(":")
        if len(parts) != 3:
            raise ValueError(f"Invalid timestamp format: {time_str}")
        hours, minutes, seconds = (int(part) for part in parts)
        return hours * 3600.0 + minutes * 60.0 + seconds

    def _read_file(self) -> None:
        """Parse the input file and store sorted requests."""
        parsed = []
        try:
            with open(self.input_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    if len(parts) < 3:
                        continue
                    try:
                        ts = self._parse_timestamp(parts[0])
                        port = int(parts[1])
                        value = int(parts[2])
                    except ValueError:
                        continue
                    
                    parsed.append({
                        "input_time": ts,
                        "port": port,
                        "value": value
                    })
        except FileNotFoundError:
            # If file not found, treat as empty schedule
            pass
            
        self.requests = sorted(parsed, key=lambda x: x["input_time"])

    def initialize(self):
        self._read_file()
        self.next_index = 0
        self.simulated_time = 0.0
        
        if not self.requests:
            self.passivate("DONE")
        else:
            # Schedule first event
            first_time = self.requests[0]["input_time"]
            self.hold_in("EMIT", max(0.0, first_time))

    def deltext(self, e: float):
        # This model has no input ports, so this is purely to handle elapsed time if needed
        # though typically passive models don't receive external events.
        # However, to be safe/standard compliant:
        self.continuef(e)

    def lambdaf(self):
        if self.phase == "EMIT" and self.next_index < len(self.requests):
            req = self.requests[self.next_index]
            
            # 1. Send business request via request_out
            self.output["request_out"].add({
                "input_time": req["input_time"],
                "port": req["port"],
                "value": req["value"]
            })
            
            # 2. Send input observation via input_fact_out
            # Message format: '{port value}'
            message = f"{{{req['port']} {req['value']}}}"
            self.output["input_fact_out"].add({
                "time": req["input_time"],
                "component": "input_reader",
                "message": message
            })

    def deltint(self):
        # Advance simulation time by the sigma that just elapsed
        self.simulated_time += self.sigma
        
        # Move to next request
        self.next_index += 1
        
        if self.next_index >= len(self.requests):
            self.passivate("DONE")
        else:
            next_req = self.requests[self.next_index]
            delay = next_req["input_time"] - self.simulated_time
            self.hold_in("EMIT", max(0.0, delay))

    def exit(self):
        pass