#!/usr/bin/env python3
"""
Secure Area Access Control with PIN Authentication
Discrete Event Simulation Implementation
"""

import argparse
import json
import sys
from datetime import datetime
from typing import List, Dict, Any, Tuple
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
        
        # Events storage
        self.events = []
        self.operations = []
        
        # Simulation environment
        self.env = simpy.Environment()
        
        # Track when alarm admin becomes free
        self.alarm_admin_free_time = 0.0
        
        # Store all input requests for processing
        self.input_requests = []
        
    def parse_timestamp(self, timestamp_str: str) -> float:
        """Convert HH:MM:SS timestamp to seconds"""
        h, m, s = map(int, timestamp_str.split(':'))
        return h * 3600 + m * 60 + s
    
    def process_input_request(self, input_time: float, value: int):
        """Process an input request"""
        # Record input reader event
        message = f"{{0 {value}}}"
        self.events.append({
            "time": input_time,
            "component": "input_reader",
            "message": message
        })
        
        # Check if alarm admin is busy
        if input_time < self.alarm_admin_free_time:
            # Ignore the request
            self.operations.append({
                "input_time": input_time,
                "action": "disarm" if value == 0 else "arm",
                "completed": False,
                "completion_time": None
            })
            return
            
        # Accept the request
        self.operations.append({
            "input_time": input_time,
            "action": "disarm" if value == 0 else "arm",
            "completed": True,
            "completion_time": None  # Will be filled when authentication completes
        })
        
        # Schedule alarm admin event
        self.env.process(self.alarm_admin(input_time, value))
        
    def alarm_admin(self, input_time: float, value: int):
        """Process alarm admin delay"""
        yield self.env.timeout(self.alarm_admin_delay)
        
        # Emit alarm admin event
        message = f"{{0 {value}}}"
        self.events.append({
            "time": input_time + self.alarm_admin_delay,
            "component": "alarmAdmin",
            "message": message
        })
        
        # Schedule authentication
        self.env.process(self.authentication(input_time, value))
        
    def authentication(self, input_time: float, value: int):
        """Process authentication delay"""
        yield self.env.timeout(self.authentication_delay)
        
        # Update system state
        if value == 1:  # Arm
            self.state = "Armed"
        else:  # Disarm
            self.state = "Disarmed"
            
        # Emit authentication event
        auth_state = "ArmValid" if value == 1 else "DisarmValid"
        message = f"{{0 {value}}}"
        self.events.append({
            "time": input_time + self.alarm_admin_delay + self.authentication_delay,
            "component": "authentication",
            "message": message,
            "state": auth_state
        })
        
        # Update alarm admin free time
        self.alarm_admin_free_time = input_time + self.alarm_admin_delay + self.authentication_delay
        
        # Schedule display
        self.env.process(self.display(input_time, value))
        
    def display(self, input_time: float, value: int):
        """Process display delay"""
        yield self.env.timeout(self.display_delay)
        
        # Emit display event
        display_state = "Armed" if value == 1 else "Disarmed"
        message = f"{{0 {value}}}"
        self.events.append({
            "time": input_time + self.alarm_admin_delay + self.authentication_delay + self.display_delay,
            "component": "display",
            "message": message,
            "state": display_state
        })
        
        # Update the operation completion time
        # Find the corresponding operation and update it
        for op in self.operations:
            if op["input_time"] == input_time and op["completed"]:
                op["completion_time"] = input_time + self.alarm_admin_delay + self.authentication_delay
                break
        
    def run_simulation(self, input_file: str):
        """Run the simulation with input file"""
        # Process input file and store all requests
        with open(input_file, 'r') as f:
            for line in f:
                line = line.strip()
                if not line:  # Skip blank lines
                    continue
                    
                parts = line.split()
                if len(parts) != 3:
                    continue
                    
                timestamp_str, port, value = parts
                input_time = self.parse_timestamp(timestamp_str)
                
                # Store the request for later processing
                self.input_requests.append((input_time, int(value)))
        
        # Sort input requests by time
        self.input_requests.sort(key=lambda x: x[0])
        
        # Process all input requests in order
        for input_time, value in self.input_requests:
            self.process_input_request(input_time, value)
        
        # Run simulation
        self.env.run(until=self.max_simulation_time)
        
        # Sort events by time
        self.events.sort(key=lambda x: x['time'])
        
        # Calculate final simulation time
        if self.events:
            # Find the latest display event time
            display_times = [event['time'] for event in self.events if event['component'] == 'display']
            if display_times:
                self.final_simulation_time = max(display_times)
            else:
                self.final_simulation_time = self.env.now
        else:
            self.final_simulation_time = 0.0


def main():
    parser = argparse.ArgumentParser(description='Secure Area Access Control Simulation')
    parser.add_argument('--test_name', required=True, help='Test name to include in output')
    parser.add_argument('--input_file', help='Input request file path')
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
        system.run_simulation(args.input_file)
    
    # Prepare output
    output = {
        "test_name": args.test_name,
        "simulation_time": system.final_simulation_time if hasattr(system, 'final_simulation_time') else 0.0,
        "initial_state": "Disarmed",
        "final_state": system.state,
        "events": system.events,
        "operations": system.operations
    }
    
    # Print JSON output to stdout
    print(json.dumps(output))


if __name__ == "__main__":
    main()