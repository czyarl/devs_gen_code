import argparse
import json
import sys
import logging
from datetime import datetime
from typing import List, Tuple, Optional

# Configure logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(message)s')

class Event:
    def __init__(self, time: float, component: str, message: str, state: Optional[str] = None):
        self.time = time
        self.component = component
        self.message = message
        self.state = state

    def to_dict(self):
        result = {
            "time": self.time,
            "component": self.component,
            "message": self.message
        }
        if self.state is not None:
            result["state"] = self.state
        return result

class Operation:
    def __init__(self, input_time: float, action: str, completed: bool, completion_time: Optional[float]):
        self.input_time = input_time
        self.action = action
        self.completed = completed
        self.completion_time = completion_time

    def to_dict(self):
        return {
            "input_time": self.input_time,
            "action": self.action,
            "completed": self.completed,
            "completion_time": self.completion_time
        }

class AlarmSystem:
    def __init__(self, 
                 alarm_admin_delay: float = 10.0,
                 authentication_delay: float = 2.0,
                 display_delay: float = 3.0,
                 max_simulation_time: float = 1000.0):
        self.alarm_admin_delay = alarm_admin_delay
        self.authentication_delay = authentication_delay
        self.display_delay = display_delay
        self.max_simulation_time = max_simulation_time
        self.state = "Disarmed"
        self.currently_working = False
        self.events: List[Event] = []
        self.operations: List[Operation] = []
        self.simulation_time = 0.0

    def parse_time(self, time_str: str) -> float:
        """Parse HH:MM:SS format to seconds"""
        h, m, s = map(int, time_str.split(':'))
        return h * 3600 + m * 60 + s

    def process_input(self, time: float, port: int, value: int):
        """Process an input request"""
        # Record input_reader event
        message = f"{{{port} {value}}}"
        self.events.append(Event(time, "input_reader", message))
        
        # Check if system is currently working
        if self.currently_working:
            # Ignore the request
            self.operations.append(Operation(time, "arm" if value == 1 else "disarm", False, None))
            return
        
        # Accept the request
        self.currently_working = True
        action = "arm" if value == 1 else "disarm"
        self.operations.append(Operation(time, action, True, None))
        
        # Schedule alarmAdmin event
        admin_time = time + self.alarm_admin_delay
        self.events.append(Event(admin_time, "alarmAdmin", message))
        
        # Schedule authentication event
        auth_time = admin_time + self.authentication_delay
        state = "ArmValid" if value == 1 else "DisarmValid"
        self.events.append(Event(auth_time, "authentication", message, state))
        
        # Schedule display event
        display_time = auth_time + self.display_delay
        display_state = "Armed" if value == 1 else "Disarmed"
        self.events.append(Event(display_time, "display", message, display_state))
        
        # Update state
        self.state = display_state
        
        # Update completion time for operation
        self.operations[-1].completion_time = auth_time
        
        # Mark as not working after authentication
        self.simulation_time = max(self.simulation_time, display_time)

    def run_simulation(self, input_file: str):
        """Run the simulation with input from file"""
        # Read and process input file
        with open(input_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                
                parts = line.split()
                if len(parts) != 3:
                    continue
                
                time_str, port_str, value_str = parts
                time = self.parse_time(time_str)
                port = int(port_str)
                value = int(value_str)
                
                self.process_input(time, port, value)
        
        # Sort events by time
        self.events.sort(key=lambda x: x.time)
        
        # Final simulation time is the time of the last display event
        if self.events:
            final_display_time = max(e.time for e in self.events if e.component == "display")
            self.simulation_time = final_display_time
        else:
            self.simulation_time = 0.0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_name", required=True, type=str)
    parser.add_argument("--input_file", required=True, type=str)
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0)
    parser.add_argument("--authentication_delay", type=float, default=2.0)
    parser.add_argument("--display_delay", type=float, default=3.0)
    parser.add_argument("--max_simulation_time", type=float, default=1000.0)
    
    args = parser.parse_args()
    
    # Create system
    system = AlarmSystem(
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    
    # Run simulation
    system.run_simulation(args.input_file)
    
    # Prepare output
    output = {
        "test_name": args.test_name,
        "simulation_time": system.simulation_time,
        "initial_state": "Disarmed",
        "final_state": system.state,
        "events": [event.to_dict() for event in system.events],
        "operations": [op.to_dict() for op in system.operations]
    }
    
    # Print JSON to stdout
    print(json.dumps(output))

if __name__ == "__main__":
    main()