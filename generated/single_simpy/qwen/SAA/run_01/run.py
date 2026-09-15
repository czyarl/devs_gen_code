import argparse
import json
import sys
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

# Configure logging to stderr
logging.basicConfig(level=logging.INFO, format='%(message)s', stream=sys.stderr)

class Event:
    def __init__(self, time: float, component: str, message: str, state: Optional[str] = None):
        self.time = time
        self.component = component
        self.message = message
        self.state = state
    
    def to_dict(self) -> Dict[str, Any]:
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
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "input_time": self.input_time,
            "action": self.action,
            "completed": self.completed,
            "completion_time": self.completion_time
        }

def parse_time(time_str: str) -> float:
    """Parse HH:MM:SS format to seconds."""
    h, m, s = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s

def read_input_file(filename: str) -> List[Dict[str, Any]]:
    """Read input file and return list of requests."""
    requests = []
    try:
        with open(filename, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) != 3:
                    logging.warning(f"Ignoring invalid line {line_num}: {line}")
                    continue
                try:
                    timestamp, port, value = parts
                    time_sec = parse_time(timestamp)
                    port = int(port)
                    value = int(value)
                    if port != 0 or value not in [0, 1]:
                        logging.warning(f"Ignoring invalid line {line_num}: {line}")
                        continue
                    requests.append({
                        "time": time_sec,
                        "port": port,
                        "value": value
                    })
                except ValueError:
                    logging.warning(f"Ignoring invalid line {line_num}: {line}")
                    continue
    except FileNotFoundError:
        logging.error(f"Input file not found: {filename}")
        sys.exit(1)
    return requests

def simulate(test_name: str, 
             input_file: str,
             alarm_admin_delay: float,
             authentication_delay: float,
             display_delay: float,
             max_simulation_time: float) -> Dict[str, Any]:
    
    # Initialize simulation state
    current_state = "Disarmed"
    simulation_time = 0.0
    events: List[Event] = []
    operations: List[Operation] = []
    
    # Read input requests
    requests = read_input_file(input_file)
    
    # Sort requests by time
    requests.sort(key=lambda x: x["time"])
    
    # Track if alarm admin is busy
    alarm_admin_busy_until = -1.0  # Time when alarm admin becomes free
    
    # Process each request
    for req in requests:
        input_time = req["time"]
        value = req["value"]
        message = f"{{{req['port']} {value}}}"
        
        # Record input reader event
        events.append(Event(input_time, "input_reader", message))
        
        # Check if alarm admin is available
        if input_time < alarm_admin_busy_until:
            # Request ignored
            operations.append(Operation(
                input_time=input_time,
                action="disarm" if value == 0 else "arm",
                completed=False,
                completion_time=None
            ))
            continue
        
        # Accept the request
        operations.append(Operation(
            input_time=input_time,
            action="disarm" if value == 0 else "arm",
            completed=True,
            completion_time=None  # Will be set later
        ))
        
        # Schedule events
        alarm_admin_time = input_time + alarm_admin_delay
        auth_time = alarm_admin_time + authentication_delay
        display_time = auth_time + display_delay
        
        # Set completion time for operation
        operations[-1].completion_time = auth_time
        
        # Update alarm admin busy time
        alarm_admin_busy_until = auth_time
        
        # Add alarm admin event
        events.append(Event(alarm_admin_time, "alarmAdmin", message))
        
        # Add authentication event
        state = "DisarmValid" if value == 0 else "ArmValid"
        events.append(Event(auth_time, "authentication", message, state))
        
        # Add display event
        display_state = "Disarmed" if value == 0 else "Armed"
        events.append(Event(display_time, "display", message, display_state))
        
        # Update current state
        current_state = display_state
    
    # Sort events by time
    events.sort(key=lambda e: e.time)
    
    # Find final simulation time
    final_simulation_time = simulation_time
    if events:
        final_simulation_time = max(e.time for e in events)
    
    # Ensure we don't exceed max simulation time
    if final_simulation_time > max_simulation_time:
        final_simulation_time = max_simulation_time
    
    # Prepare output
    result = {
        "test_name": test_name,
        "simulation_time": final_simulation_time,
        "initial_state": "Disarmed",
        "final_state": current_state,
        "events": [e.to_dict() for e in events],
        "operations": [op.to_dict() for op in operations]
    }
    
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--test_name", required=True, type=str)
    parser.add_argument("--input_file", required=True, type=str)
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0)
    parser.add_argument("--authentication_delay", type=float, default=2.0)
    parser.add_argument("--display_delay", type=float, default=3.0)
    parser.add_argument("--max_simulation_time", type=float, default=1000.0)
    
    args = parser.parse_args()
    
    result = simulate(
        test_name=args.test_name,
        input_file=args.input_file,
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    
    print(json.dumps(result))

if __name__ == "__main__":
    main()