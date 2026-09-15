import argparse
import json
import sys
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

def parse_hms(hms_str):
    h, m, s = map(int, hms_str.split(':'))
    return h * 3600 + m * 60 + s

class SimulationLogger:
    def __init__(self):
        self.events = []
        self.operations = {}
        self.max_event_time = 0.0

    def add_event(self, time, component, message, state=None):
        event = {"time": time, "component": component, "message": message}
        if state is not None:
            event["state"] = state
        self.events.append(event)
        if time > self.max_event_time:
            self.max_event_time = time

    def register_operation(self, input_time, action):
        self.operations[input_time] = {
            "input_time": input_time,
            "action": action,
            "completed": False,
            "completion_time": None
        }

    def complete_operation(self, input_time, completion_time):
        if input_time in self.operations:
            self.operations[input_time]["completed"] = True
            self.operations[input_time]["completion_time"] = completion_time

class InputReader(Atomic):
    def __init__(self, name, parent, input_file, logger):
        super().__init__(name)
        self.logger = logger
        self.out_port = Port(object, "out")
        self.add_out_port(self.out_port)
        
        self.inputs = []
        if input_file:
            with open(input_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    parts = line.split()
                    t_str, port, val = parts[0], parts[1], parts[2]
                    self.inputs.append((parse_hms(t_str), port, val))
        self.inputs.sort(key=lambda x: x[0])
        self.idx = 0
        self.pending = None

    def initialize(self):
        if self.idx < len(self.inputs):
            t = self.inputs[self.idx][0]
            self.hold_in("active", t)
        else:
            self.passivate()

    def deltext(self, e):
        pass

    def deltint(self):
        if self.phase == "active":
            t, port, val = self.inputs[self.idx]
            msg = f"{{{port} {val}}}"
            self.logger.add_event(t, "input_reader", msg)
            
            action = "arm" if val == "1" else "disarm"
            self.logger.register_operation(t, action)
            
            self.pending = {"time": t, "port": port, "value": val}
            self.idx += 1
            
            if self.idx < len(self.inputs):
                next_t = self.inputs[self.idx][0]
                self.hold_in("active", next_t - t)
            else:
                self.passivate()

    def lambdaf(self):
        if self.phase == "active" and self.pending:
            self.out_port.add(self.pending)
            self.pending = None

    def exit(self):
        pass

class AlarmAdmin(Atomic):
    def __init__(self, name, parent, logger, admin_delay, auth_delay):
        super().__init__(name)
        self.logger = logger
        self.admin_delay = admin_delay
        self.auth_delay = auth_delay
        
        self.in_port = Port(object, "in")
        self.out_port = Port(object, "out")
        self.add_in_port(self.in_port)
        self.add_out_port(self.out_port)
        
        self.pending = None
        self.current_req = None

    def initialize(self):
        self.passivate()

    def deltext(self, e):
        if self.phase == "passive":
            if self.in_port.values:
                self.current_req = self.in_port.values[0]
                self.hold_in("processing", self.admin_delay)
        # If busy, ignore

    def deltint(self):
        if self.phase == "processing":
            t_event = self.current_req["time"] + self.admin_delay
            msg = f"{{{self.current_req['port']} {self.current_req['value']}}}"
            self.logger.add_event(t_event, "alarmAdmin", msg)
            
            self.pending = self.current_req
            self.hold_in("waiting", self.auth_delay)
        elif self.phase == "waiting":
            self.passivate()

    def lambdaf(self):
        if self.phase == "processing" and self.pending:
            self.out_port.add(self.pending)
            self.pending = None

    def exit(self):
        pass

class Authentication(Atomic):
    def __init__(self, name, parent, logger, admin_delay, auth_delay):
        super().__init__(name)
        self.logger = logger
        self.admin_delay = admin_delay
        self.auth_delay = auth_delay
        
        self.in_port = Port(object, "in")
        self.out_port = Port(object, "out")
        self.add_in_port(self.in_port)
        self.add_out_port(self.out_port)
        
        self.pending = None
        self.current_req = None

    def initialize(self):
        self.passivate()

    def deltext(self, e):
        if self.in_port.values:
            self.current_req = self.in_port.values[0]
            self.hold_in("validating", self.auth_delay)

    def deltint(self):
        if self.phase == "validating":
            t_event = self.current_req["time"] + self.admin_delay + self.auth_delay
            msg = f"{{{self.current_req['port']} {self.current_req['value']}}}"
            state_str = "ArmValid" if self.current_req["value"] == "1" else "DisarmValid"
            self.logger.add_event(t_event, "authentication", msg, state_str)
            
            self.logger.complete_operation(self.current_req["time"], t_event)
            
            self.pending = self.current_req
            self.passivate()

    def lambdaf(self):
        if self.phase == "validating" and self.pending:
            self.out_port.add(self.pending)
            self.pending = None

    def exit(self):
        pass

class Display(Atomic):
    def __init__(self, name, parent, logger, admin_delay, auth_delay, display_delay):
        super().__init__(name)
        self.logger = logger
        self.admin_delay = admin_delay
        self.auth_delay = auth_delay
        self.display_delay = display_delay
        
        self.in_port = Port(object, "in")
        self.add_in_port(self.in_port)
        
        self.state = "Disarmed"
        self.current_req = None

    def initialize(self):
        self.passivate()

    def deltext(self, e):
        if self.in_port.values:
            self.current_req = self.in_port.values[0]
            self.hold_in("updating", self.display_delay)

    def deltint(self):
        if self.phase == "updating":
            if self.current_req["value"] == "1":
                self.state = "Armed"
            else:
                self.state = "Disarmed"
            
            t_event = self.current_req["time"] + self.admin_delay + self.auth_delay + self.display_delay
            msg = f"{{{self.current_req['port']} {self.current_req['value']}}}"
            self.logger.add_event(t_event, "display", msg, self.state)
            
            self.passivate()

    def lambdaf(self):
        pass

    def exit(self):
        pass

class SecureAreaSystem(Coupled):
    def __init__(self, name, parent, logger, input_file, admin_delay, auth_delay, display_delay):
        super().__init__(name)
        
        self.logger = logger
        
        self.reader = InputReader("reader", self, input_file, logger)
        self.admin = AlarmAdmin("admin", self, logger, admin_delay, auth_delay)
        self.auth = Authentication("auth", self, logger, admin_delay, auth_delay)
        self.display = Display("display", self, logger, admin_delay, auth_delay, display_delay)
        
        self.add_component(self.reader)
        self.add_component(self.admin)
        self.add_component(self.auth)
        self.add_component(self.display)
        
        self.add_coupling(self.reader.out_port, self.admin.in_port)
        self.add_coupling(self.admin.out_port, self.auth.in_port)
        self.add_coupling(self.auth.out_port, self.display.in_port)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_name", type=str, required=True)
    parser.add_argument("--input_file", type=str, required=False)
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0)
    parser.add_argument("--authentication_delay", type=float, default=2.0)
    parser.add_argument("--display_delay", type=float, default=3.0)
    parser.add_argument("--max_simulation_time", type=float, default=1000.0)
    args = parser.parse_args()

    logger = SimulationLogger()
    
    root = SecureAreaSystem(
        "SecureAreaSystem", 
        None, 
        logger, 
        args.input_file, 
        args.alarm_admin_delay, 
        args.authentication_delay, 
        args.display_delay
    )
    
    clock = SimulationClock()
    coord = Coordinator(root, clock=clock)
    coord.initialize()
    coord.simulate_time(args.max_simulation_time)
    
    events = sorted(logger.events, key=lambda x: x["time"])
    operations = sorted(logger.operations.values(), key=lambda x: x["input_time"])
    
    final_state = root.display.state
    
    if logger.max_event_time < args.max_simulation_time:
        sim_time = logger.max_event_time
    else:
        sim_time = args.max_simulation_time
        
    output = {
        "test_name": args.test_name,
        "simulation_time": sim_time,
        "initial_state": "Disarmed",
        "final_state": final_state,
        "events": events,
        "operations": operations
    }
    
    print(json.dumps(output))

if __name__ == "__main__":
    main()