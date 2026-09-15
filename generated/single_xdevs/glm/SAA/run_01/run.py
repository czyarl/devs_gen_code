import argparse
import sys
import json
import logging
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Configure logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger("SecureAreaSimulation")

# Global event and operation lists to be populated by models
simulation_events = []
simulation_operations = []
final_system_state = "Disarmed"

def parse_timestamp(ts_str):
    parts = ts_str.split(':')
    h, m, s = int(parts[0]), int(parts[1]), int(parts[2])
    return h * 3600 + m * 60 + s

class InputReader(Atomic):
    def __init__(self, name: str, parent: Coupled | None, input_file: str):
        super().__init__(name)
        self.parent = parent
        self.input_file = input_file
        self.out_request = Port(object, "out_request")
        self.add_out_port(self.out_request)
        
        self.requests = []
        self.idx = 0
        self.current_time = 0.0

    def initialize(self):
        self.requests = []
        self.idx = 0
        self.current_time = 0.0
        
        try:
            with open(self.input_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    if len(parts) >= 3:
                        t = parse_timestamp(parts[0])
                        self.requests.append({"time": t, "port": parts[1], "value": parts[2]})
                        action = "disarm" if parts[2] == '0' else "arm"
                        simulation_operations.append({
                            "input_time": t,
                            "action": action,
                            "completed": False,
                            "completion_time": None
                        })
            self.requests.sort(key=lambda x: x["time"])
            
            if self.requests:
                sigma = self.requests[0]["time"] - self.current_time
                self.hold_in("ACTIVE", sigma)
            else:
                self.hold_in("DONE", float('inf'))
        except Exception as e:
            logger.error(f"Error reading input file: {e}")
            self.hold_in("DONE", float('inf'))

    def deltint(self):
        self.current_time += self.sigma
        self.idx += 1
        if self.idx < len(self.requests):
            next_time = self.requests[self.idx]["time"]
            sigma = next_time - self.current_time
            self.hold_in("ACTIVE", sigma)
        else:
            self.hold_in("DONE", float('inf'))

    def lambdaf(self):
        if self.phase == "ACTIVE":
            req = self.requests[self.idx]
            msg = f"{{{req['port']} {req['value']}}}"
            simulation_events.append({
                "time": self.current_time + self.sigma,
                "component": "input_reader",
                "message": msg
            })
            self.out_request.add(req)

    def deltext(self, e):
        self.current_time += e
        pass

    def exit(self):
        pass

class AlarmAdmin(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        
        self.in_request = Port(object, "in_request")
        self.add_in_port(self.in_request)
        
        self.out_auth = Port(object, "out_auth")
        self.add_out_port(self.out_auth)
        
        self.current_request = None
        self.current_time = 0.0

    def initialize(self):
        self.current_time = 0.0
        self.current_request = None
        self.hold_in("IDLE", float('inf'))

    def deltint(self):
        self.current_time += self.sigma
        if self.phase == "PROCESSING":
            self.current_request = None
            self.hold_in("IDLE", float('inf'))

    def deltext(self, e):
        self.current_time += e
        if self.phase == "IDLE":
            if self.in_request.values:
                self.current_request = self.in_request.values[0]
                self.hold_in("PROCESSING", self.delay)

    def lambdaf(self):
        if self.phase == "PROCESSING":
            event_time = self.current_time + self.sigma
            req = self.current_request
            msg = f"{{{req['port']} {req['value']}}}"
            simulation_events.append({
                "time": event_time,
                "component": "alarmAdmin",
                "message": msg
            })
            self.out_auth.add(req)

    def exit(self):
        pass

class Authentication(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        
        self.in_auth = Port(object, "in_auth")
        self.add_in_port(self.in_auth)
        
        self.out_display = Port(object, "out_display")
        self.add_out_port(self.out_display)
        
        self.current_request = None
        self.current_time = 0.0

    def initialize(self):
        self.current_time = 0.0
        self.current_request = None
        self.hold_in("IDLE", float('inf'))

    def deltint(self):
        self.current_time += self.sigma
        if self.phase == "VALIDATING":
            self.current_request = None
            self.hold_in("IDLE", float('inf'))

    def deltext(self, e):
        self.current_time += e
        if self.phase == "IDLE":
            if self.in_auth.values:
                self.current_request = self.in_auth.values[0]
                self.hold_in("VALIDATING", self.delay)

    def lambdaf(self):
        if self.phase == "VALIDATING":
            event_time = self.current_time + self.sigma
            req = self.current_request
            state_str = "DisarmValid" if req['value'] == '0' else "ArmValid"
            msg = f"{{{req['port']} {req['value']}}}"
            simulation_events.append({
                "time": event_time,
                "component": "authentication",
                "message": msg,
                "state": state_str
            })
            self.out_display.add(req)

    def exit(self):
        pass

class Display(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        
        self.in_display = Port(object, "in_display")
        self.add_in_port(self.in_display)
        
        self.current_request = None
        self.current_time = 0.0

    def initialize(self):
        self.current_time = 0.0
        self.current_request = None
        self.hold_in("IDLE", float('inf'))

    def deltint(self):
        self.current_time += self.sigma
        if self.phase == "UPDATING":
            req = self.current_request
            global final_system_state
            if req['value'] == '0':
                final_system_state = "Disarmed"
            else:
                final_system_state = "Armed"
            self.current_request = None
            self.hold_in("IDLE", float('inf'))

    def deltext(self, e):
        self.current_time += e
        if self.phase == "IDLE":
            if self.in_display.values:
                self.current_request = self.in_display.values[0]
                self.hold_in("UPDATING", self.delay)

    def lambdaf(self):
        if self.phase == "UPDATING":
            event_time = self.current_time + self.sigma
            req = self.current_request
            state_str = "Disarmed" if req['value'] == '0' else "Armed"
            msg = f"{{{req['port']} {req['value']}}}"
            simulation_events.append({
                "time": event_time,
                "component": "display",
                "message": msg,
                "state": state_str
            })
            
            input_t = req['time']
            for op in simulation_operations:
                if op['input_time'] == input_t:
                    if not op['completed']:
                        op['completed'] = True
                        op['completion_time'] = event_time
                    break

    def exit(self):
        pass

class SecureAreaSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None, input_file: str, 
                 admin_delay: float, auth_delay: float, display_delay: float):
        super().__init__(name)
        self.parent = parent
        
        self.reader = InputReader("InputReader", self, input_file)
        self.admin = AlarmAdmin("AlarmAdmin", self, admin_delay)
        self.auth = Authentication("Authentication", self, auth_delay)
        self.disp = Display("Display", self, display_delay)
        
        self.add_component(self.reader)
        self.add_component(self.admin)
        self.add_component(self.auth)
        self.add_component(self.disp)
        
        self.add_coupling(self.reader.out_request, self.admin.in_request)
        self.add_coupling(self.admin.out_auth, self.auth.in_auth)
        self.add_coupling(self.auth.out_display, self.disp.in_display)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_name", type=str, required=True)
    parser.add_argument("--input_file", type=str, required=True)
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0)
    parser.add_argument("--authentication_delay", type=float, default=2.0)
    parser.add_argument("--display_delay", type=float, default=3.0)
    parser.add_argument("--max_simulation_time", type=float, default=1000.0)
    
    args = parser.parse_args()
    
    global simulation_events, simulation_operations, final_system_state
    simulation_events = []
    simulation_operations = []
    final_system_state = "Disarmed"
    
    root = SecureAreaSystem(
        name="SecureAreaSystem",
        parent=None,
        input_file=args.input_file,
        admin_delay=args.alarm_admin_delay,
        auth_delay=args.authentication_delay,
        display_delay=args.display_delay
    )
    
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.max_simulation_time)
    
    simulation_events.sort(key=lambda x: x["time"])
    simulation_operations.sort(key=lambda x: x["input_time"])
    
    sim_time = args.max_simulation_time
    if simulation_events:
        last_event_time = simulation_events[-1]["time"]
        if last_event_time < args.max_simulation_time:
            sim_time = last_event_time
        else:
            sim_time = args.max_simulation_time
    else:
        sim_time = 0.0

    output = {
        "test_name": args.test_name,
        "simulation_time": sim_time,
        "initial_state": "Disarmed",
        "final_state": final_system_state,
        "events": simulation_events,
        "operations": simulation_operations
    }
    
    print(json.dumps(output))

if __name__ == "__main__":
    main()