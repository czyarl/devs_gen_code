"""Atomic DEVS model: OutdoorTempSource."""

import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class OutdoorTempSource(Atomic):
    """Reads the timestamped outdoor temperature schedule from stdin once at initialization.
    At each integer time from 1 through int(simulate_time), it determines the effective
    outdoor temperature based on the greatest timestamp <= current time (defaulting to 25.0
    if none exists) and sends this value to the RoomModel.
    """

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        simulate_time: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.simulate_time = simulate_time

        # Output port for the outdoor temperature
        self.add_out_port(Port(float, "outdoor_temp_out"))

        # Storage for the parsed schedule: list of (timestamp_seconds, temperature_float)
        self.schedule = []

    @staticmethod
    def _parse_timestamp(time_text: str) -> float:
        """Convert HH:MM:SS string to seconds since midnight."""
        hours, minutes, seconds = (float(part) for part in time_text.split(":"))
        return hours * 3600.0 + minutes * 60.0 + seconds

    def _read_schedule(self) -> None:
        """Read all non-empty lines from stdin and parse them into the schedule."""
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            try:
                parts = line.split()
                # Expect format: HH:MM:SS <temperature>
                time_text = parts[0]
                temp_text = parts[1]
                
                timestamp = self._parse_timestamp(time_text)
                temperature = float(temp_text)
                
                self.schedule.append((timestamp, temperature))
            except (ValueError, IndexError):
                # Skip malformed lines as per standard robust reading
                continue
        
        # Sort by timestamp to ensure correct lookup order
        self.schedule.sort(key=lambda x: x[0])

    def _get_temperature_at(self, current_time: float) -> float:
        """Determine the effective outdoor temperature at the current simulation time.
        
        Uses the reading with the greatest timestamp <= current_time.
        Defaults to 25.0 if no such reading exists.
        """
        # Default value if schedule is empty or all timestamps are in the future
        effective_temp = 25.0
        
        for timestamp, temp in self.schedule:
            if timestamp > current_time:
                break
            effective_temp = temp
            
        return effective_temp

    def initialize(self):
        """Read stdin and schedule the first output event."""
        self._read_schedule()
        
        # The first output is required at t=1.
        # If simulate_time is < 1, we passivate immediately.
        if self.simulate_time >= 1.0:
            self.hold_in("EMIT", 1.0)
        else:
            self.passivate("DONE")

    def deltext(self, e: float):
        """Handle external input (none expected for this model)."""
        self.continuef(e)

    def lambdaf(self):
        """Emit the current outdoor temperature to the output port."""
        if self.phase == "EMIT":
            current_time = get_current_time()
            temp = self._get_temperature_at(current_time)
            self.output["outdoor_temp_out"].add(temp)

    def deltint(self):
        """Schedule the next output event or passivate if simulation time is reached."""
        current_time = get_current_time()
        
        # Check if we need to schedule another event for the next integer second
        # The last time we output is int(simulate_time).
        # If current_time + 1 <= int(simulate_time), we schedule next.
        if current_time + 1.0 <= int(self.simulate_time):
            self.hold_in("EMIT", 1.0)
        else:
            self.passivate("DONE")

    def exit(self):
        """Cleanup (no specific resources to release)."""
        pass