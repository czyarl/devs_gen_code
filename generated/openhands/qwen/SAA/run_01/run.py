#!/usr/bin/env python3
"""
Secure Area Access Control Simulation
"""

import argparse
import json
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional
import simpy


class SecureAreaSystem:
    def __init__(self, alarm_admin_delay: float = 10.0, 
                 authentication_delay: float = 2.0, 
                 display_delay: float = 3.0,
                 max_simulation_time: float = 1000.0):
        self.alarm_admin_delay = alarm_admin_delay
        self.authentication_delay = authentication_delay
        self.display_delay = display_delay
        self.max_simulation_time = max_simulation_time
        
        # System state
        self.state = "Disarmed"
        
        # Events list
        self.events = []
        
        # Operations list
        self.operations = []
        
        # Simulation environment
        self.env = simpy.Environment()
        
        # Track if admin is busy
        self.admin_busy = False
        
        # Track when admin will be free
        self.admin_free_time = 0.0
        
    def parse_timestamp(self, timestamp_str: str) -> float:
        """Parse HH:MM:SS timestamp to seconds."""
        h, m, s = map(int, timestamp_str.split(':'))
        return h * 3600 + m * 60 + s
    
    def process_input_request(self, input_time: float, value: int):
        """Process an input request."""
        # Record input reader event - this happens for ALL requests
        self.events.append({
            "time": float(input_time),
            "component": "input_reader",
            "message": f"{{{input_time} {value}}}"
        })
        
        # Check if admin is busy
        if self.admin_busy and input_time < self.admin_free_time:
            # Ignore the request - no further events
            self.operations.append({
                "input_time": float(input_time),
                "action": "disarm" if value == 0 else "arm",
                "completed": False,
                "completion_time": None
            })
            return
        
        # Accept the request
        self.admin_busy = True
        action = "disarm" if value == 0 else "arm"
        
        # Record alarmAdmin event
        alarm_admin_time = input_time + self.alarm_admin_delay
        self.events.append({
            "time": float(alarm_admin_time),
            "component": "alarmAdmin",
            "message": f"{{{input_time} {value}}}"
        })
        
        # Record authentication event
        auth_time = alarm_admin_time + self.authentication_delay
        state = "DisarmValid" if value == 0 else "ArmValid"
        self.events.append({
            "time": float(auth_time),
            "component": "authentication",
            "message": f"{{{input_time} {value}}}",
            "state": state
        })
        
        # Record display event
        display_time = auth_time + self.display_delay
        display_state = "Disarmed" if value == 0 else "Armed"
        self.events.append({
            "time": float(display_time),
            "component": "display",
            "message": f"{{{input_time} {value}}}",
            "state": display_state
        })
        
        # Update system state
        if value == 1:  # Arm
            self.state = "Armed"
        elif value == 0:  # Disarm
            self.state = "Disarmed"
            
        # Record operation
        self.operations.append({
            "input_time": float(input_time),
            "action": action,
            "completed": True,
            "completion_time": float(auth_time)
        })
        
        # Set admin as free after authentication delay
        self.admin_free_time = float(auth_time)
        self.env.process(self.release_admin(auth_time))
    
    def release_admin(self, release_time: float):
        """Release admin after processing."""
        yield self.env.timeout(release_time - self.env.now)
        self.admin_busy = False
    
    def run_simulation(self, input_file: str, test_name: str):
        """Run the simulation with input file."""
        # Read input file
        with open(input_file, 'r') as f:
            lines = f.readlines()
        
        # Process each line
        for line in lines:
            line = line.strip()
            if not line:  # Skip blank lines
                continue
                
            parts = line.split()
            if len(parts) != 3:
                continue
                
            timestamp_str, port, value = parts
            if port != '0':
                continue
                
            input_time = self.parse_timestamp(timestamp_str)
            value = int(value)
            
            # Schedule the input request
            self.env.process(self.schedule_input_request(input_time, value))
        
        # Run simulation
        self.env.run(until=self.max_simulation_time)
        
        # Sort events by time
        self.events.sort(key=lambda x: x['time'])
        
        # Determine final simulation time
        final_simulation_time = self.max_simulation_time
        if self.events:
            final_simulation_time = max(event['time'] for event in self.events)
        
        # Return results
        return {
            "test_name": test_name,
            "simulation_time": float(final_simulation_time),
            "initial_state": "Disarmed",
            "final_state": self.state,
            "events": self.events,
            "operations": self.operations
        }
    
    def schedule_input_request(self, input_time: float, value: int):
        """Schedule an input request at specific time."""
        yield self.env.timeout(input_time - self.env.now)
        self.process_input_request(input_time, value)


def main():
    parser = argparse.ArgumentParser(description='Secure Area Access Control Simulation')
    parser.add_argument('--test_name', required=True, type=str, help='Test name to include in output')
    parser.add_argument('--input_file', type=str, help='Input request file path')
    parser.add_argument('--alarm_admin_delay', type=float, default=10.0, help='Alarm admin delay')
    parser.add_argument('--authentication_delay', type=float, default=2.0, help='Authentication delay')
    parser.add_argument('--display_delay', type=float, default=3.0, help='Display delay')
    parser.add_argument('--max_simulation_time', type=float, default=1000.0, help='Maximum simulation time')
    
    args = parser.parse_args()
    
    # Create system
    system = SecureAreaSystem(
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    
    # Run simulation
    if args.input_file:
        result = system.run_simulation(args.input_file, args.test_name)
    else:
        # If no input file, create a basic test case
        result = {
            "test_name": args.test_name,
            "simulation_time": 0.0,
            "initial_state": "Disarmed",
            "final_state": "Disarmed",
            "events": [],
            "operations": []
        }
    
    # Print result to stdout
    print(json.dumps(result))


if __name__ == "__main__":
    main()