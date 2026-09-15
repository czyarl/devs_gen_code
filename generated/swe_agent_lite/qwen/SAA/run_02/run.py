#!/usr/bin/env python3
"""
Secure Area Access Control with PIN Authentication
"""

import argparse
import json
import sys
from datetime import datetime
from collections import defaultdict

# Event types
INPUT_READER = "input_reader"
ALARM_ADMIN = "alarmAdmin"
AUTHENTICATION = "authentication"
DISPLAY = "display"

class SecureAreaSimulator:
    def __init__(self, alarm_admin_delay=10.0, authentication_delay=2.0, 
                 display_delay=3.0, max_simulation_time=1000.0):
        self.alarm_admin_delay = alarm_admin_delay
        self.authentication_delay = authentication_delay
        self.display_delay = display_delay
        self.max_simulation_time = max_simulation_time
        
        # Simulation state
        self.current_time = 0.0
        self.state = "Disarmed"
        self.is_working = False  # AlarmAdmin is working on a request
        
        # Events and operations tracking
        self.events = []
        self.operations = []
        
        # For tracking the last completed operation time
        self.last_completion_time = 0.0
        
    def parse_timestamp(self, timestamp_str):
        """Parse HH:MM:SS format to seconds"""
        h, m, s = map(int, timestamp_str.split(':'))
        return h * 3600 + m * 60 + s
    
    def process_input(self, input_time, value):
        """Process an input request"""
        # Record input_reader event
        self.events.append({
            "time": input_time,
            "component": INPUT_READER,
            "message": f"{{{input_time} {value}}}"
        })
        
        # Check if AlarmAdmin is already working
        if self.is_working:
            # Ignore the request
            self.operations.append({
                "input_time": input_time,
                "action": "disarm" if value == 0 else "arm",
                "completed": False,
                "completion_time": None
            })
            return
        
        # Accept the request
        self.is_working = True
        action = "disarm" if value == 0 else "arm"
        
        # Record alarmAdmin event
        alarm_admin_time = input_time + self.alarm_admin_delay
        self.events.append({
            "time": alarm_admin_time,
            "component": ALARM_ADMIN,
            "message": f"{{{input_time} {value}}}"
        })
        
        # Record authentication event
        auth_time = alarm_admin_time + self.authentication_delay
        state = "DisarmValid" if value == 0 else "ArmValid"
        self.events.append({
            "time": auth_time,
            "component": AUTHENTICATION,
            "message": f"{{{input_time} {value}}}",
            "state": state
        })
        
        # Update state
        if value == 1:  # arm
            self.state = "Armed"
        else:  # disarm
            self.state = "Disarmed"
            
        # Record display event
        display_time = auth_time + self.display_delay
        display_state = "Disarmed" if value == 0 else "Armed"
        self.events.append({
            "time": display_time,
            "component": DISPLAY,
            "message": f"{{{input_time} {value}}}",
            "state": display_state
        })
        
        # Update tracking
        self.last_completion_time = auth_time
        self.operations.append({
            "input_time": input_time,
            "action": action,
            "completed": True,
            "completion_time": auth_time
        })
        
        # Reset working status when authentication is complete
        self.is_working = False
    
    def run_simulation(self, input_file):
        """Run the simulation with input from file"""
        with open(input_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:  # Skip empty lines
                    continue
                    
                # Parse line: HH:MM:SS 0 value
                parts = line.split()
                if len(parts) != 3:
                    continue
                    
                timestamp_str, port, value_str = parts
                if port != "0":
                    continue
                    
                input_time = self.parse_timestamp(timestamp_str)
                value = int(value_str)
                
                # Process the input
                self.process_input(input_time, value)
                
                # Check if we've exceeded max simulation time
                if input_time > self.max_simulation_time:
                    break
        
        # Sort events by time
        self.events.sort(key=lambda x: x["time"])
        
        # Determine final simulation time
        if self.events:
            final_time = max(event["time"] for event in self.events)
        else:
            final_time = self.current_time
            
        # If the last completion time is after max simulation time, 
        # we need to adjust the final time
        if self.last_completion_time > self.max_simulation_time:
            final_time = self.max_simulation_time
            
        # Prepare output
        output = {
            "test_name": args.test_name,
            "simulation_time": final_time,
            "initial_state": "Disarmed",
            "final_state": self.state,
            "events": self.events,
            "operations": self.operations
        }
        
        # Print JSON to stdout
        print(json.dumps(output))

def main():
    parser = argparse.ArgumentParser(description="Secure Area Access Control Simulator")
    parser.add_argument("--test_name", required=True, help="Test name to include in output")
    parser.add_argument("--input_file", help="Input request file path")
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0, help="Alarm admin delay in seconds")
    parser.add_argument("--authentication_delay", type=float, default=2.0, help="Authentication delay in seconds")
    parser.add_argument("--display_delay", type=float, default=3.0, help="Display delay in seconds")
    parser.add_argument("--max_simulation_time", type=float, default=1000.0, help="Maximum simulation time in seconds")
    
    global args
    args = parser.parse_args()
    
    # Create simulator
    simulator = SecureAreaSimulator(
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    
    # Run simulation
    if args.input_file:
        simulator.run_simulation(args.input_file)
    else:
        # If no input file, create an empty simulation
        simulator.run_simulation(None)

if __name__ == "__main__":
    main()