#!/usr/bin/env python3
"""
Secure Area Access Control with PIN Authentication
Discrete Event Simulation implementation
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
        self.is_admin_working = False
        
        # Events and operations tracking
        self.events = []
        self.operations = []
        
        # Simulation environment
        self.env = simpy.Environment()
        
    def parse_timestamp(self, timestamp_str: str) -> float:
        """Convert HH:MM:SS timestamp to seconds"""
        h, m, s = map(int, timestamp_str.split(':'))
        return h * 3600 + m * 60 + s
    
    def read_input_file(self, filename: str) -> List[Tuple[float, int]]:
        """Read input file and return list of (time, value) tuples"""
        requests = []
        try:
            with open(filename, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:  # Skip empty lines
                        continue
                    parts = line.split()
                    if len(parts) >= 3:
                        timestamp = parts[0]
                        port = int(parts[1])
                        value = int(parts[2])
                        if port == 0:  # Only process port 0
                            time = self.parse_timestamp(timestamp)
                            requests.append((time, value))
        except FileNotFoundError:
            print(f"Error: Input file '{filename}' not found.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error reading input file: {e}", file=sys.stderr)
            sys.exit(1)
        return requests
    
    def input_reader(self, time: float, value: int):
        """Handle input reader event"""
        self.events.append({
            "time": time,
            "component": "input_reader",
            "message": f"{{{time} {value}}}"
        })
        
        # Check if admin is already working
        if self.is_admin_working:
            # Ignore the request
            self.operations.append({
                "input_time": time,
                "action": "disarm" if value == 0 else "arm",
                "completed": False,
                "completion_time": None
            })
            return
        
        # Accept the request
        self.is_admin_working = True
        self.operations.append({
            "input_time": time,
            "action": "disarm" if value == 0 else "arm",
            "completed": True,
            "completion_time": None  # Will be set later
        })
        
        # Schedule alarmAdmin event
        admin_time = time + self.alarm_admin_delay
        self.env.process(self.alarm_admin(admin_time, value))
    
    def alarm_admin(self, time: float, value: int):
        """Handle alarm admin event"""
        self.events.append({
            "time": time,
            "component": "alarmAdmin",
            "message": f"{{{time} {value}}}"
        })
        
        # Schedule authentication event
        auth_time = time + self.authentication_delay
        self.env.process(self.authentication(auth_time, value))
    
    def authentication(self, time: float, value: int):
        """Handle authentication event"""
        # Update operation completion time
        for op in self.operations:
            if op["input_time"] == time - self.alarm_admin_delay - self.authentication_delay:
                op["completion_time"] = time
                break
        
        # Set authentication state
        state = "DisarmValid" if value == 0 else "ArmValid"
        self.events.append({
            "time": time,
            "component": "authentication",
            "message": f"{{{time} {value}}}",
            "state": state
        })
        
        # Update system state
        if value == 1:  # Arm
            self.state = "Armed"
        else:  # Disarm
            self.state = "Disarmed"
        
        # Schedule display event
        display_time = time + self.display_delay
        self.env.process(self.display(display_time, value))
        
        # Admin is now free
        self.is_admin_working = False
    
    def display(self, time: float, value: int):
        """Handle display event"""
        # Set display state
        state = "Armed" if value == 1 else "Disarmed"
        self.events.append({
            "time": time,
            "component": "display",
            "message": f"{{{time} {value}}}",
            "state": state
        })
    
    def run_simulation(self, input_file: str, test_name: str):
        """Run the complete simulation"""
        # Read input requests
        requests = self.read_input_file(input_file)
        
        # Sort requests by time
        requests.sort(key=lambda x: x[0])
        
        # Process each request
        for time, value in requests:
            self.input_reader(time, value)
        
        # Run simulation until max time or all events are processed
        self.env.run(until=self.max_simulation_time)
        
        # Sort events by time
        self.events.sort(key=lambda x: x["time"])
        
        # Determine final simulation time
        final_simulation_time = self.max_simulation_time
        if self.events:
            final_simulation_time = max(event["time"] for event in self.events)
        
        # Return results
        return {
            "test_name": test_name,
            "simulation_time": final_simulation_time,
            "initial_state": "Disarmed",
            "final_state": self.state,
            "events": self.events,
            "operations": self.operations
        }


def main():
    parser = argparse.ArgumentParser(description='Secure Area Access Control Simulation')
    parser.add_argument('--test_name', required=True, help='Test name to include in output')
    parser.add_argument('--input_file', help='Input request file path')
    parser.add_argument('--alarm_admin_delay', type=float, default=10.0, help='Alarm admin delay in seconds')
    parser.add_argument('--authentication_delay', type=float, default=2.0, help='Authentication delay in seconds')
    parser.add_argument('--display_delay', type=float, default=3.0, help='Display delay in seconds')
    parser.add_argument('--max_simulation_time', type=float, default=1000.0, help='Maximum simulation time in seconds')
    
    args = parser.parse_args()
    
    # Create system and run simulation
    system = SecureAreaSystem(
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    
    # Run simulation
    result = system.run_simulation(args.input_file, args.test_name)
    
    # Print result as JSON to stdout
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()