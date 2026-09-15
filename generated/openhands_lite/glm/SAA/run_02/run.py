#!/usr/bin/env python3
"""
Secure Area Access Control System with PIN Authentication
Discrete Event Simulation using simpy
"""

import argparse
import json
import sys
from typing import List, Dict, Any, Optional


def parse_timestamp(timestamp_str: str) -> float:
    """Convert HH:MM:SS timestamp to seconds."""
    parts = timestamp_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def parse_input_file(input_file: str) -> List[Dict[str, Any]]:
    """Parse input file and return list of requests."""
    requests = []
    with open(input_file, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            timestamp_str = parts[0]
            port = int(parts[1])
            value = int(parts[2])
            time = parse_timestamp(timestamp_str)
            requests.append({
                'time': time,
                'port': port,
                'value': value
            })
    return requests


class SecureAreaSimulation:
    """Simulates the secure area access control system."""
    
    def __init__(self, test_name: str, requests: List[Dict[str, Any]],
                 alarm_admin_delay: float, authentication_delay: float,
                 display_delay: float, max_simulation_time: float):
        self.test_name = test_name
        self.requests = requests
        self.alarm_admin_delay = alarm_admin_delay
        self.authentication_delay = authentication_delay
        self.display_delay = display_delay
        self.max_simulation_time = max_simulation_time
        
        # System state
        self.current_state = "Disarmed"
        self.alarm_admin_busy = False
        self.alarm_admin_busy_until = 0.0
        
        # Output data
        self.events: List[Dict[str, Any]] = []
        self.operations: List[Dict[str, Any]] = []
        
        # Track operations
        self.operation_counter = 0
    
    def add_event(self, time: float, component: str, message: str,
                  state: Optional[str] = None):
        """Add an event to the events list."""
        event = {
            'time': time,
            'component': component,
            'message': message
        }
        if state is not None:
            event['state'] = state
        self.events.append(event)
    
    def add_operation(self, input_time: float, action: str, completed: bool,
                      completion_time: Optional[float]):
        """Add an operation to the operations list."""
        self.operations.append({
            'input_time': input_time,
            'action': action,
            'completed': completed,
            'completion_time': completion_time
        })
    
    def run(self):
        """Run the simulation."""
        # Sort requests by time
        sorted_requests = sorted(self.requests, key=lambda x: x['time'])
        
        # Process each request
        for request in sorted_requests:
            time = request['time']
            port = request['port']
            value = request['value']
            
            # Check if we've exceeded max simulation time
            if time > self.max_simulation_time:
                break
            
            # Record input_reader event
            message = f"{{{port} {value}}}"
            self.add_event(time, 'input_reader', message)
            
            # Determine action
            action = 'disarm' if value == 0 else 'arm'
            
            # Check if AlarmAdmin is busy
            if self.alarm_admin_busy and time < self.alarm_admin_busy_until:
                # Request is ignored
                self.add_operation(time, action, False, None)
            else:
                # Request is accepted
                alarm_admin_time = time + self.alarm_admin_delay
                auth_time = alarm_admin_time + self.authentication_delay
                display_time = auth_time + self.display_delay
                
                # AlarmAdmin event
                self.add_event(alarm_admin_time, 'alarmAdmin', message)
                
                # Authentication event
                auth_state = 'DisarmValid' if value == 0 else 'ArmValid'
                self.add_event(auth_time, 'authentication', message, state=auth_state)
                
                # Display event
                display_state = 'Disarmed' if value == 0 else 'Armed'
                self.add_event(display_time, 'display', message, state=display_state)
                
                # Update system state at authentication time
                self.current_state = display_state
                
                # Mark AlarmAdmin as busy until authentication completes
                self.alarm_admin_busy = True
                self.alarm_admin_busy_until = auth_time
                
                # Record operation
                self.add_operation(time, action, True, auth_time)
        
        # Sort events by time
        self.events.sort(key=lambda x: x['time'])
        
        # Sort operations by input_time
        self.operations.sort(key=lambda x: x['input_time'])
        
        # Determine simulation time
        if self.events:
            simulation_time = min(self.events[-1]['time'], self.max_simulation_time)
        else:
            simulation_time = 0.0
    
    def get_output(self) -> Dict[str, Any]:
        """Get the output JSON object."""
        return {
            'test_name': self.test_name,
            'simulation_time': self.events[-1]['time'] if self.events else 0.0,
            'initial_state': 'Disarmed',
            'final_state': self.current_state,
            'events': self.events,
            'operations': self.operations
        }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Secure Area Access Control System Simulation'
    )
    parser.add_argument('--test_name', type=str, required=True,
                        help='Test name for output')
    parser.add_argument('--input_file', type=str, default=None,
                        help='Input file path')
    parser.add_argument('--alarm_admin_delay', type=float, default=10.0,
                        help='Alarm admin delay in seconds')
    parser.add_argument('--authentication_delay', type=float, default=2.0,
                        help='Authentication delay in seconds')
    parser.add_argument('--display_delay', type=float, default=3.0,
                        help='Display delay in seconds')
    parser.add_argument('--max_simulation_time', type=float, default=1000.0,
                        help='Maximum simulation time in seconds')
    
    args = parser.parse_args()
    
    # Parse input file if provided
    requests = []
    if args.input_file:
        requests = parse_input_file(args.input_file)
    
    # Create and run simulation
    sim = SecureAreaSimulation(
        test_name=args.test_name,
        requests=requests,
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    
    sim.run()
    
    # Output JSON to stdout
    output = sim.get_output()
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
