#!/usr/bin/env python3
"""
Secure Area Access Control System with PIN Authentication
"""

import argparse
import json
import sys
from datetime import datetime
from collections import deque


class Event:
    def __init__(self, time, component, message, state=None):
        self.time = time
        self.component = component
        self.message = message
        self.state = state
    
    def to_dict(self):
        result = {
            'time': self.time,
            'component': self.component,
            'message': self.message
        }
        if self.state is not None:
            result['state'] = self.state
        return result


class Operation:
    def __init__(self, input_time, action, completed, completion_time):
        self.input_time = input_time
        self.action = action
        self.completed = completed
        self.completion_time = completion_time
    
    def to_dict(self):
        return {
            'input_time': self.input_time,
            'action': self.action,
            'completed': self.completed,
            'completion_time': self.completion_time
        }


class SecureAreaSystem:
    def __init__(self, alarm_admin_delay=10.0, authentication_delay=2.0, 
                 display_delay=3.0, max_simulation_time=1000.0):
        self.alarm_admin_delay = alarm_admin_delay
        self.authentication_delay = authentication_delay
        self.display_delay = display_delay
        self.max_simulation_time = max_simulation_time
        
        # System state
        self.current_state = "Disarmed"
        
        # Events and operations tracking
        self.events = []
        self.operations = []
        self.simulation_time = 0.0
        
        # Request queue for handling concurrent requests
        self.request_queue = deque()
        self.is_working = False  # Flag to indicate if alarm admin is processing a request
        
        # For tracking the last accepted operation
        self.last_accepted_operation_time = 0.0
    
    def parse_timestamp(self, timestamp_str):
        """Parse HH:MM:SS format to seconds"""
        h, m, s = map(int, timestamp_str.split(':'))
        return h * 3600 + m * 60 + s
    
    def process_input_line(self, line):
        """Process a single input line from the file"""
        if not line.strip():
            return
            
        parts = line.strip().split()
        if len(parts) != 3:
            return
            
        timestamp_str, port, value = parts
        timestamp_seconds = self.parse_timestamp(timestamp_str)
        
        # Validate port and value
        if int(port) != 0:
            return
            
        value_int = int(value)
        if value_int not in [0, 1]:
            return
            
        # Record input reader event
        input_message = f"{{{timestamp_seconds} {value_int}}}"
        self.events.append(Event(timestamp_seconds, "input_reader", input_message))
        
        # Check if we can accept this request
        if self.is_working:
            # Request is ignored
            operation = Operation(
                input_time=timestamp_seconds,
                action="disarm" if value_int == 0 else "arm",
                completed=False,
                completion_time=None
            )
            self.operations.append(operation)
        else:
            # Accept the request
            self.is_working = True
            self.request_queue.append((timestamp_seconds, value_int))
            
            # Schedule alarmAdmin event
            alarm_admin_time = timestamp_seconds + self.alarm_admin_delay
            alarm_admin_message = f"{{{timestamp_seconds} {value_int}}}"
            self.events.append(Event(alarm_admin_time, "alarmAdmin", alarm_admin_message))
            
            # Schedule authentication event
            auth_time = alarm_admin_time + self.authentication_delay
            auth_message = f"{{{timestamp_seconds} {value_int}}}"
            auth_state = "DisarmValid" if value_int == 0 else "ArmValid"
            self.events.append(Event(auth_time, "authentication", auth_message, auth_state))
            
            # Update system state
            if value_int == 1:
                self.current_state = "Armed"
            else:
                self.current_state = "Disarmed"
            
            # Schedule display event
            display_time = auth_time + self.display_delay
            display_message = f"{{{timestamp_seconds} {value_int}}}"
            display_state = "Armed" if value_int == 1 else "Disarmed"
            self.events.append(Event(display_time, "display", display_message, display_state))
            
            # Record operation
            operation = Operation(
                input_time=timestamp_seconds,
                action="disarm" if value_int == 0 else "arm",
                completed=True,
                completion_time=auth_time
            )
            self.operations.append(operation)
            
            # Update last accepted operation time
            self.last_accepted_operation_time = auth_time
    
    def run_simulation(self, input_file_path):
        """Run the simulation with input from file"""
        try:
            with open(input_file_path, 'r') as f:
                for line in f:
                    self.process_input_line(line)
        except FileNotFoundError:
            print(f"Error: Input file '{input_file_path}' not found.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error reading input file: {e}", file=sys.stderr)
            sys.exit(1)
        
        # Sort events by time
        self.events.sort(key=lambda x: x.time)
        
        # Determine final simulation time
        if self.events:
            # Final simulation time is the time of the last display event
            # or max_simulation_time if exceeded
            last_display_time = 0.0
            for event in reversed(self.events):
                if event.component == "display":
                    last_display_time = event.time
                    break
            self.simulation_time = min(last_display_time, self.max_simulation_time)
        else:
            self.simulation_time = 0.0
    
    def generate_output(self, test_name):
        """Generate the final JSON output"""
        # Sort events by time
        self.events.sort(key=lambda x: x.time)
        
        # Sort operations by input_time
        self.operations.sort(key=lambda x: x.input_time)
        
        output = {
            "test_name": test_name,
            "simulation_time": self.simulation_time,
            "initial_state": "Disarmed",
            "final_state": self.current_state,
            "events": [event.to_dict() for event in self.events],
            "operations": [operation.to_dict() for operation in self.operations]
        }
        
        return json.dumps(output, separators=(',', ':'))


def main():
    parser = argparse.ArgumentParser(description='Secure Area Access Control System')
    parser.add_argument('--test_name', required=True, help='Test name to include in output')
    parser.add_argument('--input_file', help='Input request file path')
    parser.add_argument('--alarm_admin_delay', type=float, default=10.0, help='Alarm admin delay in seconds')
    parser.add_argument('--authentication_delay', type=float, default=2.0, help='Authentication delay in seconds')
    parser.add_argument('--display_delay', type=float, default=3.0, help='Display delay in seconds')
    parser.add_argument('--max_simulation_time', type=float, default=1000.0, help='Maximum simulation time in seconds')
    
    args = parser.parse_args()
    
    # Create system instance
    system = SecureAreaSystem(
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    
    # Run simulation
    if args.input_file:
        system.run_simulation(args.input_file)
    else:
        # If no input file, just run with no operations
        pass
    
    # Generate and print output
    output_json = system.generate_output(args.test_name)
    print(output_json)


if __name__ == "__main__":
    main()