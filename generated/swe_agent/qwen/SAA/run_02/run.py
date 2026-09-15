#!/usr/bin/env python3
"""
Secure Area Access Control with PIN Authentication
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
        
        self.state = "Disarmed"
        self.simulation_time = 0.0
        self.events = []
        self.operations = []
        self.alarm_admin_working = False
        
    def parse_timestamp(self, timestamp_str):
        """Parse HH:MM:SS format to seconds"""
        h, m, s = map(int, timestamp_str.split(':'))
        return h * 3600 + m * 60 + s
    
    def process_input_line(self, line):
        """Process a single input line"""
        if not line.strip():
            return
            
        parts = line.strip().split()
        if len(parts) != 3:
            return
            
        timestamp_str, port, value = parts
        time = self.parse_timestamp(timestamp_str)
        port = int(port)
        value = int(value)
        
        # Record input_reader event for ALL requests
        message = f"{{{time} {value}}}"
        self.events.append(Event(time, "input_reader", message))
        
        # Check if we can process this request
        if self.alarm_admin_working:
            # Request is ignored
            self.operations.append(Operation(time, "arm" if value == 1 else "disarm", False, None))
        else:
            # Process the request
            self.alarm_admin_working = True
            self.operations.append(Operation(time, "arm" if value == 1 else "disarm", True, None))
            
            # Schedule alarmAdmin event
            alarm_admin_time = time + self.alarm_admin_delay
            message = f"{{{time} {value}}}"
            self.events.append(Event(alarm_admin_time, "alarmAdmin", message))
            
            # Schedule authentication event
            auth_time = alarm_admin_time + self.authentication_delay
            state = "ArmValid" if value == 1 else "DisarmValid"
            message = f"{{{time} {value}}}"
            self.events.append(Event(auth_time, "authentication", message, state))
            
            # Schedule display event
            display_time = auth_time + self.display_delay
            state = "Armed" if value == 1 else "Disarmed"
            message = f"{{{time} {value}}}"
            self.events.append(Event(display_time, "display", message, state))
            
            # Update system state
            if value == 1:
                self.state = "Armed"
            else:
                self.state = "Disarmed"
            
            # Update completion time for operation
            self.operations[-1].completion_time = auth_time
            
            # Reset alarm admin working status when authentication is done
            # This is handled by the event processing system
    
    def run_simulation(self, input_file):
        """Run the simulation with input from file"""
        with open(input_file, 'r') as f:
            for line in f:
                self.process_input_line(line)
        
        # Sort events by time
        self.events.sort(key=lambda x: x.time)
        
        # Determine final simulation time
        if self.events:
            final_event_time = self.events[-1].time
            self.simulation_time = min(final_event_time, self.max_simulation_time)
        else:
            self.simulation_time = 0.0

def main():
    parser = argparse.ArgumentParser(description='Secure Area Access Control with PIN Authentication')
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
        'test_name': args.test_name,
        'simulation_time': system.simulation_time,
        'initial_state': 'Disarmed',
        'final_state': system.state,
        'events': [event.to_dict() for event in system.events],
        'operations': [operation.to_dict() for operation in system.operations]
    }
    
    # Print JSON to stdout
    print(json.dumps(output))

if __name__ == '__main__':
    main()