import sys
import argparse
import json
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

def parse_outdoor_schedule():
    """
    Reads outdoor temperature schedule from stdin.
    Returns a list of (timestamp_seconds, temperature) tuples sorted by time.
    """
    schedule = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        time_str = parts[0]
        temp = float(parts[1])
        
        try:
            h, m, s = map(int, time_str.split(':'))
            total_sec = h * 3600 + m * 60 + s
            schedule.append((total_sec, temp))
        except ValueError:
            # Skip malformed lines
            continue
            
    schedule.sort(key=lambda x: x[0])
    return schedule

def get_outdoor_temp(schedule, t):
    """
    For simulation time t, returns the outdoor temperature with the greatest 
    timestamp <= t. Returns 25.0 if no such reading exists.
    """
    # Iterate backwards to find the greatest timestamp <= t
    for ts, temp in reversed(schedule):
        if ts <= t:
            return temp
    return 25.0

class HouseModel(Atomic):
    def __init__(self, name: str, parent: Coupled | None, schedule):
        super().__init__(name)
        self.parent = parent
        self.schedule = schedule
        
        # Initial state at time 0
        self.time_sec = 0
        self.room_temp_c = 25.0
        self.control_signal = 0
        self.heater_output_c = 0.0
        self.heat_loss_temp_c = 25.0

    def initialize(self):
        # Calculate state for t=1 immediately so lambdaf at t=1 outputs correct data
        self.step_dynamics()
        self.hold_in("active", 1.0)

    def step_dynamics(self):
        """
        Calculates the state for the next time step (t+1) based on current state (t).
        """
        # Current state values (at time t)
        prev_room_temp = self.room_temp_c
        prev_control = self.control_signal
        t_prev = self.time_sec
        
        # 1. Determine effective outdoor temperature
        outdoor_raw = get_outdoor_temp(self.schedule, t_prev)
        effective_outdoor = min(outdoor_raw, prev_room_temp)
        
        # 2. Calculate heat loss
        # "The room then loses 10 percent of the gap between its previous temperature 
        # and that effective outdoor temperature."
        loss = 0.1 * (prev_room_temp - effective_outdoor)
        loss_temp = prev_room_temp - loss
        
        # 3. Calculate heater gain
        # "Heater gain is delayed by one step: the heater adds 0.5 degrees during 
        # the current step only if the previous control signal was 1"
        gain = 0.5 if prev_control == 1 else 0.0
        
        # 4. Calculate new room temperature
        new_room_temp = loss_temp + gain
        
        # 5. Determine next control signal
        # "sets the next control signal to 1 when the room is below 24.9"
        new_control = 1 if new_room_temp < 24.9 else 0
        
        # Update state variables to reflect the new time t+1
        self.heat_loss_temp_c = loss_temp
        self.heater_output_c = gain
        self.room_temp_c = new_room_temp
        self.control_signal = new_control
        self.time_sec += 1

    def lambdaf(self):
        # Output JSONL record for the current time step
        # We only output for t >= 1
        if self.time_sec > 0:
            record = {
                "time_sec": self.time_sec,
                "room_temp_c": self.room_temp_c,
                "heat_loss_temp_c": self.heat_loss_temp_c,
                "control_signal": self.control_signal,
                "heater_output_c": self.heater_output_c
            }
            print(json.dumps(record), file=sys.stdout, flush=True)

    def deltint(self):
        # Prepare for the next second
        self.step_dynamics()
        self.hold_in("active", 1.0)

    def deltext(self, e):
        # No external inputs expected in this scenario
        pass

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, schedule):
        super().__init__(name)
        self.parent = parent
        self.house = HouseModel(name="house", parent=self, schedule=schedule)
        self.add_component(self.house)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=float, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()

    schedule = parse_outdoor_schedule()
    
    root = System(name="system", parent=None, schedule=schedule)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    
    coord.simulate_time(args.simulate_time)

if __name__ == "__main__":
    main()