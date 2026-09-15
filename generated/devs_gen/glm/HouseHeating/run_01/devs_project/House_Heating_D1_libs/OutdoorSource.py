import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class OutdoorSource(Atomic):
    """
    Atomic DEVS model for OutdoorSource.
    Reads a temperature schedule from stdin and emits the appropriate temperature
    at each integer simulation time step.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulate_time: float,
        default_outdoor_temp: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.simulate_time = simulate_time
        self.default_outdoor_temp = default_outdoor_temp
        
        # Register output port
        self.add_out_port(Port(float, "outdoor_temp_out"))
        
        # Internal storage for the schedule: list of (timestamp_seconds, temperature_float)
        self.schedule = []

    @staticmethod
    def _parse_time(time_text: str) -> int:
        """Convert HH:MM:SS string to integer seconds from midnight."""
        parts = time_text.split(":")
        if len(parts) != 3:
            raise ValueError("Invalid time format")
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        return hours * 3600 + minutes * 60 + seconds

    def _read_schedule(self) -> None:
        """Read all non-empty lines from stdin and parse them into a sorted schedule."""
        records = []
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                parts = line.split()
                if len(parts) < 2:
                    continue
                time_text = parts[0]
                value_text = parts[1]
                
                timestamp = self._parse_time(time_text)
                temperature = float(value_text)
                
                records.append((timestamp, temperature))
            except (ValueError, IndexError):
                # Skip malformed lines as per requirements
                continue
        
        # Sort by timestamp
        self.schedule = sorted(records, key=lambda x: x[0])

    def _get_temperature_at(self, t: int) -> float:
        """
        Find the temperature associated with the greatest timestamp ts such that ts <= t.
        If no such timestamp exists, return default_outdoor_temp.
        """
        selected_temp = self.default_outdoor_temp
        # Iterate through sorted schedule. Since it's sorted, we can update selected_temp
        # until we pass the target time.
        for ts, temp in self.schedule:
            if ts > t:
                break
            selected_temp = temp
        return selected_temp

    def initialize(self):
        """Read stdin schedule and schedule the first output event."""
        self._read_schedule()
        
        # The simulation clock advances in integer steps.
        # At each integer time t from 1 through int(simulate_time), we emit.
        # We schedule the first event at t=1.
        limit = int(self.simulate_time)
        if limit >= 1:
            self.hold_in("EMIT", 1.0)
        else:
            self.passivate("DONE")

    def deltext(self, e: float):
        """Handle external inputs (none defined for this model)."""
        self.continuef(e)

    def lambdaf(self):
        """Emit the outdoor temperature at the current simulation time."""
        if self.phase == "EMIT":
            current_time = get_current_time()
            # The contract specifies integer steps t from 1 through int(simulate_time).
            # We query the schedule using the current time.
            # Note: get_current_time() returns float, but we treat steps as integers.
            # The logic "greatest timestamp ts such that ts <= t" works with t as float or int.
            temp = self._get_temperature_at(int(current_time))
            self.output["outdoor_temp_out"].add(temp)

    def deltint(self):
        """Schedule the next emission or passivate if finished."""
        if self.phase == "EMIT":
            current_time = get_current_time()
            limit = int(self.simulate_time)
            
            # If we just emitted at time t, the next emission is at t+1.
            # We check if t+1 <= limit.
            if current_time + 1.0 <= limit:
                self.hold_in("EMIT", 1.0)
            else:
                self.passivate("DONE")

    def exit(self):
        """Cleanup."""
        pass