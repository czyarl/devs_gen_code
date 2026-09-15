"""HouseHeatingProcess: Atomic DEVS model for house heating simulation."""

import json
import sys

from xdevs.models import Atomic, Coupled, Port


class HouseHeatingProcess(Atomic):
    """
    Encapsulates the entire house heating simulation logic.
    Reads schedule from stdin, simulates temperature dynamics, writes JSONL to stdout.
    """

    def __init__(self, name: str, parent: Coupled | None, simulate_time: float):
        super().__init__(name)
        self.parent = parent
        self.simulate_time = int(simulate_time)
        
        # No DEVS ports required for this model as per contract
        # self.input and self.output remain empty dicts

        # Internal state
        self.schedule = {}  # map seconds -> temp
        self.room_temp = 25.0
        self.control_signal = 0
        self.current_step = 1  # Tracks the next integer time t to process (1 to simulate_time)

    def _read_schedule(self) -> None:
        """Reads HH:MM:SS <temp> from stdin and populates self.schedule."""
        for raw_line in sys.stdin:
            line = raw_line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            
            time_str = parts[0]
            try:
                temp_val = float(parts[1])
            except ValueError:
                continue
            
            # Parse HH:MM:SS
            time_parts = time_str.split(":")
            if len(time_parts) != 3:
                continue
            
            try:
                h = int(time_parts[0])
                m = int(time_parts[1])
                s = int(time_parts[2])
                total_seconds = h * 3600 + m * 60 + s
                self.schedule[total_seconds] = temp_val
            except ValueError:
                continue

    def _get_outdoor_temp(self, t: int) -> float:
        """
        Returns the effective outdoor temperature for time t.
        Finds the latest schedule entry <= t. Defaults to 25.0.
        """
        # Find the largest key <= t
        # Since schedule is a dict, we iterate. For efficiency in large schedules,
        # sorting keys once would be better, but requirements imply simple lookup.
        # Given constraints, iterating keys is acceptable.
        best_time = -1
        for ts in self.schedule:
            if ts <= t and ts > best_time:
                best_time = ts
        
        if best_time != -1:
            return self.schedule[best_time]
        return 25.0

    def initialize(self):
        self._read_schedule()
        self.room_temp = 25.0
        self.control_signal = 0
        self.current_step = 1
        
        if self.simulate_time > 0:
            # Schedule the first step at time 0.0 so it happens immediately at start of simulation
            # The output corresponds to time t=1.
            self.hold_in("PROCESSING", 0.0)
        else:
            self.passivate("DONE")

    def deltext(self, e: float):
        # No external inputs defined for this model
        self.continuef(e)

    def lambdaf(self):
        # No DEVS output ports defined for this model.
        # External IO (stdout) is handled in deltint after state calculation.
        pass

    def deltint(self):
        if self.phase == "PROCESSING":
            t = self.current_step
            
            # 1. Determine effective outdoor temperature
            # Requirement: "latest schedule entry <= t"
            raw_outdoor = self._get_outdoor_temp(t)
            
            # 2. Cap outdoor temp at current room temp
            effective_outdoor = min(raw_outdoor, self.room_temp)
            
            # 3. Calculate heat loss (10% of gap)
            gap = self.room_temp - effective_outdoor
            loss = 0.1 * gap
            temp_after_loss = self.room_temp - loss
            
            # 4. Apply heater gain based on previous control_signal
            heater_gain = 0.5 if self.control_signal == 1 else 0.0
            new_room_temp = temp_after_loss + heater_gain
            
            # 5. Determine next control signal
            next_control = 1 if new_room_temp < 24.9 else 0
            
            # 6. Emit JSONL record to stdout
            record = {
                "time_sec": t,
                "room_temp_c": new_room_temp,
                "heat_loss_temp_c": temp_after_loss,
                "control_signal": next_control,
                "heater_output_c": heater_gain
            }
            print(json.dumps(record), flush=True)
            
            # 7. Update internal state for next iteration
            self.room_temp = new_room_temp
            self.control_signal = next_control
            self.current_step += 1
            
            # 8. Schedule next step or finish
            if self.current_step <= self.simulate_time:
                # Schedule next integer step. 
                # Since we are at time t (conceptually), we want to process t+1 next.
                # In DEVS time, if we are at T, we schedule T+1 - T = 1.0 delay?
                # Or we just schedule 0.0 to chain immediately?
                # The requirements say "iterating through integer times t".
                # If we output at t, the next output is t+1.
                # The simulation time is continuous. 
                # Let's assume we want to output at simulation time t.
                # If we started at t=0 with sigma=0, we processed t=1.
                # Now we are at t=1 (simulation time). We want to process t=2.
                # We schedule sigma=1.0 so the next event happens at t=2.
                self.hold_in("PROCESSING", 1.0)
            else:
                self.passivate("DONE")

    def exit(self):
        pass