#!/usr/bin/env python3
"""
Secure Area Access Control with PIN Authentication
"""

import argparse
import json
import sys
from datetime import datetime
from collections import defaultdict
import heapq


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
        
        self.current_time = 0.0
        self.state = "Disarmed"
        self.is_admin_working = False
        self.events = []
        self.operations = []
        self.event_queue = []
        self.next_operation_id = 0
    
    def parse_time(self, time_str):
        """Parse HH:MM:SS format to seconds"""
        h, m, s = map(int, time_str.split(':'))
        return h * 3600 + m * 60 + s
    
    def process_input_line(self, line):
        """Process a single input line"""
        parts = line.strip().split()
        if len(parts) != 3:
            return False
            
        timestamp, port, value = parts
        time = self.parse_time(timestamp)
        port = int(port)
        value = int(value)
        
        if port != 0:
            return False
            
        # Create operation record
        action = "arm" if value == 1 else "disarm"
        operation = Operation(
            input_time=time,
            action=action,
            completed=False,
            completion_time=None
        )
        
        # Check if admin is already working
        if self.is_admin_working:
            # Ignore the request
            operation.completed = False
            self.operations.append(operation)
            # Record input event
            self.events.append(Event(
                time=time,
                component="input_reader",
                message=f"{{{time} {value}}}"
            ))
            return True
        
        # Accept the request
        self.is_admin_working = True
        operation.completed = True
        operation.completion_time = time + self.alarm_admin_delay + self.authentication_delay
        
        # Record events
        self.events.append(Event(
            time=time,
            component="input_reader",
            message=f"{{{time} {value}}}"
        ))
        
        # Schedule alarmAdmin event
        alarm_admin_time = time + self.alarm_admin_delay
        heapq.heappush(self.event_queue, (alarm_admin_time, "alarmAdmin", time, value))
        
        # Schedule authentication event
        auth_time = time + self.alarm_admin_delay + self.authentication_delay
        heapq.heappush(self.event_queue, (auth_time, "authentication", time, value))
        
        # Schedule display event
        display_time = time + self.alarm_admin_delay + self.authentication_delay + self.display_delay
        heapq.heappush(self.event_queue, (display_time, "display", time, value))
        
        self.operations.append(operation)
        return True
    
    def run_simulation(self, input_file):
        """Run the simulation with input from file"""
        # Read input file
        with open(input_file, 'r') as f:
            lines = f.readlines()
        
        # Process each line
        for line in lines:
            if line.strip() and not line.startswith('#'):
                self.process_input_line(line)
        
        # Process events in time order
        while self.event_queue:
            event_time, component, input_time, value = heapq.heappop(self.event_queue)
            
            # Check if we've exceeded max simulation time
            if event_time > self.max_simulation_time:
                break
                
            self.current_time = event_time
            
            if component == "alarmAdmin":
                self.events.append(Event(
                    time=event_time,
                    component="alarmAdmin",
                    message=f"{{{input_time} {value}}}"
                ))
            elif component == "authentication":
                # Update state
                if value == 1:
                    self.state = "Armed"
                    state_name = "ArmValid"
                else:
                    self.state = "Disarmed"
                    state_name = "DisarmValid"
                
                self.events.append(Event(
                    time=event_time,
                    component="authentication",
                    message=f"{{{input_time} {value}}}",
                    state=state_name
                ))
                
                # Admin is no longer working
                self.is_admin_working = False
            elif component == "display":
                # Update state
                if value == 1:
                    self.state = "Armed"
                else:
                    self.state = "Disarmed"
                
                self.events.append(Event(
                    time=event_time,
                    component="display",
                    message=f"{{{input_time} {value}}}",
                    state=self.state
                ))
        
        # Sort events by time
        self.events.sort(key=lambda x: x.time)
        
        # Determine final state and simulation time
        final_simulation_time = self.current_time if self.current_time <= self.max_simulation_time else self.max_simulation_time
        
        # Find the last completed operation
        last_completed_op = None
        for op in reversed(self.operations):
            if op.completed:
                last_completed_op = op
                break
        
        final_state = "Disarmed"
        if last_completed_op and last_completed_op.action == "arm":
            final_state = "Armed"
        
        # Prepare output
        output = {
            "test_name": args.test_name,
            "simulation_time": final_simulation_time,
            "initial_state": "Disarmed",
            "final_state": final_state,
            "events": [event.to_dict() for event in self.events],
            "operations": [op.to_dict() for op in self.operations]
        }
        
        # Print JSON to stdout
        print(json.dumps(output))


def main():
    parser = argparse.ArgumentParser(description='Secure Area Access Control with PIN Authentication')
    parser.add_argument('--test_name', required=True, help='Test name to include in output')
    parser.add_argument('--input_file', help='Input request file path')
    parser.add_argument('--alarm_admin_delay', type=float, default=10.0, help='Alarm admin delay')
    parser.add_argument('--authentication_delay', type=float, default=2.0, help='Authentication delay')
    parser.add_argument('--display_delay', type=float, default=3.0, help='Display delay')
    parser.add_argument('--max_simulation_time', type=float, default=1000.0, help='Maximum simulation time')
    
    global args
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
    else:
        # If no input file, create empty simulation
        system.run_simulation(None)


if __name__ == "__main__":
    main()