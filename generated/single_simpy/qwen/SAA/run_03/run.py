import argparse
import json
import sys
import logging
from datetime import datetime
from typing import List, Dict, Any, Tuple

# Configure logging to stderr
logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stderr)

class Event:
    def __init__(self, time: float, component: str, message: str, state: str = None):
        self.time = time
        self.component = component
        self.message = message
        self.state = state

class Operation:
    def __init__(self, input_time: float, action: str, completed: bool, completion_time: float = None):
        self.input_time = input_time
        self.action = action
        self.completed = completed
        self.completion_time = completion_time

class SecureAreaSimulation:
    def __init__(self, test_name: str, alarm_admin_delay: float, authentication_delay: float, 
                 display_delay: float, max_simulation_time: float):
        self.test_name = test_name
        self.alarm_admin_delay = alarm_admin_delay
        self.authentication_delay = authentication_delay
        self.display_delay = display_delay
        self.max_simulation_time = max_simulation_time
        self.simulation_time = 0.0
        self.initial_state = "Disarmed"
        self.final_state = "Disarmed"
        self.events: List[Event] = []
        self.operations: List[Operation] = []
        self.current_state = "Disarmed"
        self.admin_working = False
        self.next_completion_time = None

    def parse_time(self, time_str: str) -> float:
        """Parse HH:MM:SS format to seconds"""
        h, m, s = map(int, time_str.split(':'))
        return h * 3600 + m * 60 + s

    def read_input_file(self, filename: str) -> List[Tuple[float, int, int]]:
        """Read input file and return list of (time, port, value) tuples"""
        requests = []
        try:
            with open(filename, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    parts = line.split()
                    if len(parts) != 3:
                        continue
                    time_str, port, value = parts
                    time_sec = self.parse_time(time_str)
                    requests.append((time_sec, int(port), int(value)))
        except FileNotFoundError:
            logging.error(f"Input file {filename} not found")
            sys.exit(1)
        return requests

    def process_request(self, time: float, port: int, value: int):
        """Process a request at given time"""
        # Record input_reader event
        message = f"{{{port} {value}}}"
        self.events.append(Event(time, "input_reader", message))
        
        # Check if admin is busy
        if self.admin_working:
            # Ignore the request
            self.operations.append(Operation(time, "arm" if value == 1 else "disarm", False, None))
            logging.debug(f"Ignoring request at {time} due to admin working")
            return
        
        # Accept the request
        self.admin_working = True
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
        
        # Update completion time for operation
        self.operations[-1].completion_time = auth_time
        
        # Update system state
        self.current_state = display_state
        self.next_completion_time = auth_time
        
        logging.debug(f"Processed request at {time}: {action}")

    def run_simulation(self, input_file: str):
        """Run the complete simulation"""
        # Read input requests
        requests = self.read_input_file(input_file)
        
        # Sort requests by time
        requests.sort(key=lambda x: x[0])
        
        # Process each request
        for time, port, value in requests:
            if time > self.max_simulation_time:
                break
            self.process_request(time, port, value)
        
        # Sort events by time
        self.events.sort(key=lambda x: x.time)
        
        # Find the final simulation time
        if self.events:
            self.simulation_time = max(event.time for event in self.events)
        else:
            self.simulation_time = 0.0
        
        # Ensure we don't exceed max simulation time
        if self.simulation_time > self.max_simulation_time:
            self.simulation_time = self.max_simulation_time
        
        # Set final state based on last completed operation
        if self.operations:
            last_completed = None
            for op in reversed(self.operations):
                if op.completed:
                    last_completed = op
                    break
            if last_completed:
                self.final_state = "Armed" if last_completed.action == "arm" else "Disarmed"
            else:
                self.final_state = self.initial_state
        else:
            self.final_state = self.initial_state

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_name", required=True, type=str)
    parser.add_argument("--input_file", required=True, type=str)
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0)
    parser.add_argument("--authentication_delay", type=float, default=2.0)
    parser.add_argument("--display_delay", type=float, default=3.0)
    parser.add_argument("--max_simulation_time", type=float, default=1000.0)
    
    args = parser.parse_args()
    
    # Create simulation
    sim = SecureAreaSimulation(
        args.test_name,
        args.alarm_admin_delay,
        args.authentication_delay,
        args.display_delay,
        args.max_simulation_time
    )
    
    # Run simulation
    sim.run_simulation(args.input_file)
    
    # Prepare output
    output = {
        "test_name": sim.test_name,
        "simulation_time": sim.simulation_time,
        "initial_state": sim.initial_state,
        "final_state": sim.final_state,
        "events": [
            {
                "time": event.time,
                "component": event.component,
                "message": event.message,
                "state": event.state
            }
            for event in sim.events
        ],
        "operations": [
            {
                "input_time": op.input_time,
                "action": op.action,
                "completed": op.completed,
                "completion_time": op.completion_time
            }
            for op in sim.operations
        ]
    }
    
    # Print JSON to stdout
    print(json.dumps(output))

if __name__ == "__main__":
    main()