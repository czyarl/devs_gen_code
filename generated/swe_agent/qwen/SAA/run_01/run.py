#!/usr/bin/env python3

import argparse
import json
import sys
from datetime import datetime

class Event:
    def __init__(self, time, component, message, state=None):
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
    def __init__(self, input_time, action, completed, completion_time):
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

def parse_time(time_str):
    """Parse HH:MM:SS format to seconds"""
    h, m, s = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s

def process_request(input_time, value, alarm_admin_delay, authentication_delay, display_delay, max_simulation_time, events, operations, current_state, alarm_admin_free_time):
    """
    Process a single request and generate appropriate events.
    Returns updated state, alarm_admin_free_time, and whether the request was accepted.
    """
    # Check if alarm admin is busy
    if input_time < alarm_admin_free_time:
        # Request is ignored
        operations.append(Operation(input_time, "arm" if value == 1 else "disarm", False, None))
        return current_state, alarm_admin_free_time, False
    
    # Accept the request
    operations.append(Operation(input_time, "arm" if value == 1 else "disarm", True, None))
    
    # Generate events with proper timing
    # input_reader event
    events.append(Event(input_time, "input_reader", f"{{{input_time} {value}}}", None))
    
    # alarmAdmin event
    alarm_admin_time = input_time + alarm_admin_delay
    events.append(Event(alarm_admin_time, "alarmAdmin", f"{{{input_time} {value}}}", None))
    
    # authentication event
    auth_time = alarm_admin_time + authentication_delay
    events.append(Event(auth_time, "authentication", f"{{{input_time} {value}}}", 
                       "ArmValid" if value == 1 else "DisarmValid"))
    
    # display event
    display_time = auth_time + display_delay
    new_state = "Armed" if value == 1 else "Disarmed"
    events.append(Event(display_time, "display", f"{{{input_time} {value}}}", new_state))
    
    # Update completion time for operation
    operations[-1].completion_time = auth_time
    
    # alarm_admin_free_time is when authentication completes (when alarm admin stops working)
    new_alarm_admin_free_time = auth_time
    
    return new_state, new_alarm_admin_free_time, True

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test_name', required=True, type=str)
    parser.add_argument('--input_file', type=str)
    parser.add_argument('--alarm_admin_delay', type=float, default=10.0)
    parser.add_argument('--authentication_delay', type=float, default=2.0)
    parser.add_argument('--display_delay', type=float, default=3.0)
    parser.add_argument('--max_simulation_time', type=float, default=1000.0)
    
    args = parser.parse_args()
    
    # Read input file
    if args.input_file:
        with open(args.input_file, 'r') as f:
            lines = f.readlines()
    else:
        lines = []
    
    # Filter out blank lines and process input
    processed_lines = []
    for line in lines:
        line = line.strip()
        if line:  # Skip empty lines
            parts = line.split()
            if len(parts) >= 3:
                timestamp = parse_time(parts[0])
                port = int(parts[1])
                value = int(parts[2])
                if port == 0:  # Only process port 0
                    processed_lines.append((timestamp, value))
    
    # Sort by timestamp
    processed_lines.sort(key=lambda x: x[0])
    
    # Initialize simulation
    events = []
    operations = []
    current_state = "Disarmed"
    alarm_admin_free_time = 0.0
    simulation_time = 0.0
    
    # Process each request
    for input_time, value in processed_lines:
        # Process the request
        new_state, alarm_admin_free_time, accepted = process_request(
            input_time, value, args.alarm_admin_delay, args.authentication_delay, 
            args.display_delay, args.max_simulation_time, events, operations, 
            current_state, alarm_admin_free_time
        )
        
        if accepted:
            current_state = new_state
    
    # Sort events by time
    events.sort(key=lambda x: x.time)
    
    # Determine final simulation time
    if events:
        simulation_time = events[-1].time
    else:
        simulation_time = 0.0
    
    # Check if we hit max simulation time before all events were processed
    if simulation_time > args.max_simulation_time:
        simulation_time = args.max_simulation_time
    
    # Prepare output
    output = {
        "test_name": args.test_name,
        "simulation_time": simulation_time,
        "initial_state": "Disarmed",
        "final_state": current_state,
        "events": [event.to_dict() for event in events],
        "operations": [operation.to_dict() for operation in operations]
    }
    
    # Print to stdout
    print(json.dumps(output))

if __name__ == "__main__":
    main()