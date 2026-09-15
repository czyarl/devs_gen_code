import argparse
import sys
import json
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# --- Global Storage for Output ---
# Used to collect events and operation status across the simulation components.
collected_events = []
collected_operations = []

# --- Constants ---
PHASE_IDLE = "idle"
PHASE_BUSY = "busy"

# --- Helper Functions ---
def parse_hhmmss(time_str: str) -> float:
    """Converts HH:MM:SS string to float seconds."""
    try:
        h, m, s = map(float, time_str.split(':'))
        return h * 3600 + m * 60 + s
    except ValueError:
        return 0.0

# --- Atomic Models ---

class InputReader(Atomic):
    def __init__(self, name: str, parent: Coupled | None, input_file: str, max_time: float):
        super().__init__(name)
        self.parent = parent
        self.input_file = input_file
        self.max_time = max_time
        
        # Ports
        self.add_out_port(Port(object, "out"))
        
        # State
        self.inputs = []
        self.index = 0
        self._load_inputs()

    def _load_inputs(self):
        try:
            with open(self.input_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    if len(parts) == 3:
                        t_str, port, val = parts
                        t = parse_hhmmss(t_str)
                        # Only consider inputs within max_time (optional optimization, but good for robustness)
                        if t <= self.max_time:
                            self.inputs.append({
                                "time": t,
                                "port": int(port),
                                "value": int(val)
                            })
                            # Initialize operation record
                            action = "disarm" if int(val) == 0 else "arm"
                            collected_operations.append({
                                "input_time": t,
                                "action": action,
                                "completed": False,
                                "completion_time": None
                            })
        except FileNotFoundError:
            pass

    def initialize(self):
        if self.inputs:
            first_time = self.inputs[0]["time"]
            self.hold_in("active", first_time)
        else:
            self.hold_in("done", float('inf'))

    def lambdaf(self):
        if self.phase == "active" and self.index < len(self.inputs):
            data = self.inputs[self.index]
            self.output["out"].add(data)
            
            # Record event
            msg = f"{{{data['port']} {data['value']}}}"
            collected_events.append({
                "time": self.clock.get_time(),
                "component": "input_reader",
                "message": msg
            })

    def deltint(self):
        if self.phase == "active":
            self.index += 1
            if self.index < len(self.inputs):
                next_time = self.inputs[self.index]["time"]
                self.hold_in("active", next_time - self.clock.get_time())
            else:
                self.hold_in("done", float('inf'))
        else:
            self.hold_in("done", float('inf'))

    def deltext(self, e):
        # InputReader ignores external inputs
        pass

    def exit(self):
        pass


class AlarmAdmin(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        
        # State
        self.is_busy = False
        self.current_request = None
        
        # Ports
        self.add_in_port(Port(object, "in"))
        self.add_out_port(Port(object, "out"))

    def initialize(self):
        self.hold_in(PHASE_IDLE, float('inf'))

    def lambdaf(self):
        if self.phase == PHASE_BUSY and self.current_request:
            self.output["out"].add(self.current_request)
            
            # Record event
            msg = f"{{{self.current_request['port']} {self.current_request['value']}}}"
            collected_events.append({
                "time": self.clock.get_time(),
                "component": "alarmAdmin",
                "message": msg
            })

    def deltint(self):
        if self.phase == PHASE_BUSY:
            self.is_busy = False
            self.current_request = None
            self.hold_in(PHASE_IDLE, float('inf'))

    def deltext(self, e):
        if self.is_busy:
            # Ignore new request if busy
            pass
        else:
            if self.input["in"].values:
                req = next(iter(self.input["in"].values))
                self.is_busy = True
                self.current_request = req
                self.hold_in(PHASE_BUSY, self.delay)

    def exit(self):
        pass


class Authentication(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        
        # State
        self.current_request = None
        
        # Ports
        self.add_in_port(Port(object, "in"))
        self.add_out_port(Port(object, "out"))

    def initialize(self):
        self.hold_in(PHASE_IDLE, float('inf'))

    def lambdaf(self):
        if self.phase == PHASE_BUSY and self.current_request:
            self.output["out"].add(self.current_request)
            
            # Record event
            val = self.current_request['value']
            state_str = "DisarmValid" if val == 0 else "ArmValid"
            msg = f"{{{self.current_request['port']} {val}}}"
            
            collected_events.append({
                "time": self.clock.get_time(),
                "component": "authentication",
                "message": msg,
                "state": state_str
            })
            
            # Update operation record
            req_time = self.current_request['time']
            for op in collected_operations:
                # Match by input time and ensure not already marked (though sequential processing implies uniqueness)
                if op['input_time'] == req_time and not op['completed']:
                    op['completed'] = True
                    op['completion_time'] = self.clock.get_time()
                    break

    def deltint(self):
        if self.phase == PHASE_BUSY:
            self.current_request = None
            self.hold_in(PHASE_IDLE, float('inf'))

    def deltext(self, e):
        if self.input["in"].values:
            req = next(iter(self.input["in"].values))
            self.current_request = req
            self.hold_in(PHASE_BUSY, self.delay)

    def exit(self):
        pass


class Display(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        
        # State
        self.current_state = "Disarmed" # Initial state
        self.current_request = None
        
        # Ports
        self.add_in_port(Port(object, "in"))

    def initialize(self):
        self.hold_in(PHASE_IDLE, float('inf'))

    def lambdaf(self):
        if self.phase == PHASE_BUSY and self.current_request:
            val = self.current_request['value']
            self.current_state = "Armed" if val == 1 else "Disarmed"
            
            # Record event
            state_str = self.current_state
            msg = f"{{{self.current_request['port']} {val}}}"
            
            collected_events.append({
                "time": self.clock.get_time(),
                "component": "display",
                "message": msg,
                "state": state_str
            })

    def deltint(self):
        if self.phase == PHASE_BUSY:
            self.current_request = None
            self.hold_in(PHASE_IDLE, float('inf'))

    def deltext(self, e):
        if self.input["in"].values:
            req = next(iter(self.input["in"].values))
            self.current_request = req
            self.hold_in(PHASE_BUSY, self.delay)

    def exit(self):
        pass


# --- Coupled Model ---

class SecureAreaSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None, input_file: str,
                 alarm_admin_delay: float, authentication_delay: float,
                 display_delay: float, max_simulation_time: float):
        super().__init__(name)
        self.parent = parent
        
        # Instantiate Components
        self.input_reader = InputReader("input_reader", self, input_file, max_simulation_time)
        self.alarm_admin = AlarmAdmin("alarm_admin", self, alarm_admin_delay)
        self.authentication = Authentication("authentication", self, authentication_delay)
        self.display = Display("display", self, display_delay)
        
        # Add Components
        self.add_component(self.input_reader)
        self.add_component(self.alarm_admin)
        self.add_component(self.authentication)
        self.add_component(self.display)
        
        # Add Couplings
        self.add_coupling(self.input_reader.output["out"], self.alarm_admin.input["in"])
        self.add_coupling(self.alarm_admin.output["out"], self.authentication.input["in"])
        self.add_coupling(self.authentication.output["out"], self.display.input["in"])


# --- Main Entry Point ---

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_name", type=str, required=True)
    parser.add_argument("--input_file", type=str, required=False, default="")
    parser.add_argument("--alarm_admin_delay", type=float, required=False, default=10.0)
    parser.add_argument("--authentication_delay", type=float, required=False, default=2.0)
    parser.add_argument("--display_delay", type=float, required=False, default=3.0)
    parser.add_argument("--max_simulation_time", type=float, required=False, default=1000.0)
    
    args = parser.parse_args()
    
    # Create Root Model
    root = SecureAreaSystem(
        name="secure_area_system",
        parent=None,
        input_file=args.input_file,
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    
    # Create Coordinator
    # SimulationClock(0) initializes time at 0
    coord = Coordinator(root, clock=SimulationClock(0))
    
    # Run Simulation
    coord.initialize()
    coord.simulate_time(args.max_simulation_time)
    
    # Determine Final State
    # Based on the last completed operation
    final_state = "Disarmed"
    last_completion_time = -1.0
    
    for op in collected_operations:
        if op['completed']:
            if op['completion_time'] > last_completion_time:
                last_completion_time = op['completion_time']
                final_state = "Armed" if op['action'] == 'arm' else "Disarmed"
    
    # Determine Simulation Time
    # If simulation stopped early due to max_time, clock reflects that.
    # If it finished all events, clock reflects the time of the last event.
    sim_time = coord.clock.get_time()
    
    # Sort Events
    collected_events.sort(key=lambda x: x['time'])
    
    # Sort Operations
    collected_operations.sort(key=lambda x: x['input_time'])
    
    # Construct Output
    output = {
        "test_name": args.test_name,
        "simulation_time": sim_time,
        "initial_state": "Disarmed",
        "final_state": final_state,
        "events": collected_events,
        "operations": collected_operations
    }
    
    print(json.dumps(output))

if __name__ == "__main__":
    main()