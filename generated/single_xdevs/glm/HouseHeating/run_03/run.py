import sys
import argparse
import json
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Constants
TARGET_TEMP = 24.9
HEATER_GAIN = 0.5
LOSS_RATE = 0.1
DEFAULT_OUTDOOR = 25.0

class RoomModel(Atomic):
    def __init__(self, name: str, parent: Coupled | None, outdoor_schedule: dict, simulate_time: int):
        super().__init__(name)
        self.parent = parent
        self.outdoor_schedule = outdoor_schedule
        self.simulate_time = simulate_time
        
        # State variables
        self.time_sec = 0
        self.room_temp = 25.0
        self.control_signal = 0  # Signal for the NEXT step (initially 0)

    def initialize(self):
        # Schedule first event at t=1.0
        self.hold_in("active", 1.0)

    def get_outdoor_temp(self, t):
        # Find greatest timestamp <= t
        valid_keys = [k for k in self.outdoor_schedule.keys() if k <= t]
        if not valid_keys:
            return DEFAULT_OUTDOOR
        return self.outdoor_schedule[max(valid_keys)]

    def lambdaf(self):
        # Output function. No ports used, so nothing to do here.
        pass

    def deltint(self):
        # Internal transition
        self.time_sec += 1
        
        # Stop if we exceed the simulation duration
        if self.time_sec > self.simulate_time:
            self.hold_in("passive", float('inf'))
            return

        # 1. Determine effective outdoor temp from the previous second (t-1)
        # "First choose the effective outdoor temperature from the previous second"
        prev_t = self.time_sec - 1
        outdoor = self.get_outdoor_temp(prev_t)
        
        # Cap outdoor temp to previous room temp to prevent heat gain
        effective_outdoor = min(outdoor, self.room_temp)
        
        # 2. Calculate heat loss
        # "The room then loses 10 percent of the gap between its previous temperature and that effective outdoor temperature."
        gap = self.room_temp - effective_outdoor
        loss = LOSS_RATE * gap
        heat_loss_temp_c = self.room_temp - loss
        
        # 3. Calculate heater gain
        # "Heater gain is delayed by one step: the heater adds 0.5 degrees during the current step only if the previous control signal was 1"
        # self.control_signal currently holds the signal determined in the previous step
        heater_gain = HEATER_GAIN if self.control_signal == 1 else 0.0
        heater_output_c = heater_gain
        
        # 4. Update room temperature
        self.room_temp = heat_loss_temp_c + heater_gain
        
        # 5. Determine next control signal
        # "controller sets the next control signal to 1 when the room is below 24.9 degrees Celsius"
        next_control = 1 if self.room_temp < TARGET_TEMP else 0
        
        # 6. Output JSONL record
        record = {
            "time_sec": self.time_sec,
            "room_temp_c": self.room_temp,
            "heat_loss_temp_c": heat_loss_temp_c,
            "control_signal": next_control,
            "heater_output_c": heater_output_c
        }
        print(json.dumps(record), file=sys.stdout, flush=True)
        
        # 7. Update state for next iteration
        self.control_signal = next_control
        
        # Schedule next event
        self.hold_in("active", 1.0)

    def deltext(self, e):
        # External transition (no inputs expected)
        pass

    def exit(self):
        # Cleanup
        pass

class HeatingSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None, outdoor_schedule: dict, simulate_time: int):
        super().__init__(name)
        self.parent = parent
        
        # Instantiate the room model
        room = RoomModel(name="room", parent=self, outdoor_schedule=outdoor_schedule, simulate_time=simulate_time)
        self.add_component(room)

def parse_stdin():
    """Reads outdoor temperature schedule from stdin."""
    schedule = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        time_str = parts[0]
        temp_str = parts[1]
        
        try:
            h, m, s = map(int, time_str.split(':'))
            total_sec = h * 3600 + m * 60 + s
            temp = float(temp_str)
            schedule[total_sec] = temp
        except ValueError:
            # Skip malformed lines
            continue
    return schedule

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=float, required=True)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    outdoor_schedule = parse_stdin()
    sim_duration_int = int(args.simulate_time)

    root = HeatingSystem(name="heating_system", parent=None, outdoor_schedule=outdoor_schedule, simulate_time=sim_duration_int)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulate_time)

if __name__ == "__main__":
    main()