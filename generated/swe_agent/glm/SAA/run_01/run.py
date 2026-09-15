#!/usr/bin/env python3
"""
Secure Area Access Control with PIN Authentication
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
    # Sort by time
    requests.sort(key=lambda x: x['time'])
    return requests


class SecureAreaSimulation:
    """Simulates the secure area access control system."""
    
    def __init__(self, 
                 alarm_admin_delay: float = 10.0,
                 authentication_delay: float = 2.0,
                 display_delay: float = 3.0,
                 max_simulation_time: float = 1000.0):
        self.alarm_admin_delay = alarm_admin_delay
        self.authentication_delay = authentication_delay
        self.display_delay = display_delay
        self.max_simulation_time = max_simulation_time
        
        # System state
        self.state = "Disarmed"
        self.initial_state = "Disarmed"
        
        # Event tracking
        self.events: List[Dict[str, Any]] = []
        self.operations: List[Dict[str, Any]] = []
        
        # AlarmAdmin status
        self.alarm_admin_busy = False
        self.alarm_admin_free_time = 0.0
        
        # Simulation time
        self.simulation_time = 0.0
    
    def add_event(self, time: float, component: str, message: str, state: Optional[str] = None):
        """Add an event to the event list."""
        event = {
            'time': time,
            'component': component,
            'message': message
        }
        if state is not None:
            event['state'] = state
        self.events.append(event)
    
    def process_request(self, request: Dict[str, Any]) -> bool:
        """Process a single request. Returns True if accepted, False if ignored."""
        time = request['time']
        port = request['port']
        value = request['value']
        
        # Record input_reader event
        message = f"{{{port} {value}}}"
        self.add_event(time, 'input_reader', message)
        
        # Check if AlarmAdmin is busy
        if self.alarm_admin_busy and time < self.alarm_admin_free_time:
            # Request is ignored
            action = "disarm" if value == 0 else "arm"
            self.operations.append({
                'input_time': time,
                'action': action,
                'completed': False,
                'completion_time': None
            })
            return False
        
        # Request is accepted
        action = "disarm" if value == 0 else "arm"
        
        # AlarmAdmin outputs the request
        alarm_admin_time = time + self.alarm_admin_delay
        self.add_event(alarm_admin_time, 'alarmAdmin', message)
        
        # Authentication outputs successful validation
        auth_time = alarm_admin_time + self.authentication_delay
        auth_state = "DisarmValid" if value == 0 else "ArmValid"
        self.add_event(auth_time, 'authentication', message, state=auth_state)
        
        # Display outputs the resulting visible state
        display_time = auth_time + self.display_delay
        display_state = "Disarmed" if value == 0 else "Armed"
        self.add_event(display_time, 'display', message, state=display_state)
        
        # Update system state
        self.state = display_state
        
        # Update AlarmAdmin busy status
        self.alarm_admin_busy = True
        self.alarm_admin_free_time = auth_time
        
        # Record operation
        self.operations.append({
            'input_time': time,
            'action': action,
            'completed': True,
            'completion_time': auth_time
        })
        
        return True
    
    def run(self, requests: List[Dict[str, Any]]):
        """Run the simulation with the given requests."""
        if not requests:
            self.simulation_time = 0.0
            return
        
        # Process each request
        for request in requests:
            # Check if we've exceeded max simulation time
            if request['time'] > self.max_simulation_time:
                break
            
            self.process_request(request)
        
        # Sort events by time
        self.events.sort(key=lambda x: x['time'])
        
        # Determine final simulation time
        if self.events:
            last_event_time = self.events[-1]['time']
            self.simulation_time = min(last_event_time, self.max_simulation_time)
        else:
            self.simulation_time = 0.0
    
    def get_output(self, test_name: str) -> Dict[str, Any]:
        """Generate the output JSON."""
        return {
            'test_name': test_name,
            'simulation_time': self.simulation_time,
            'initial_state': self.initial_state,
            'final_state': self.state,
            'events': self.events,
            'operations': self.operations
        }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Secure Area Access Control Simulation')
    parser.add_argument('--test_name', type=str, required=True,
                        help='Test name copied into output JSON')
    parser.add_argument('--input_file', type=str, default=None,
                        help='Input request file path')
    parser.add_argument('--alarm_admin_delay', type=float, default=10.0,
                        help='Alarm admin delay (default: 10.0)')
    parser.add_argument('--authentication_delay', type=float, default=2.0,
                        help='Authentication delay (default: 2.0)')
    parser.add_argument('--display_delay', type=float, default=3.0,
                        help='Display delay (default: 3.0)')
    parser.add_argument('--max_simulation_time', type=float, default=1000.0,
                        help='Maximum simulation time (default: 1000.0)')
    
    args = parser.parse_args()
    
    # Parse input file
    requests = []
    if args.input_file:
        requests = parse_input_file(args.input_file)
    
    # Create and run simulation
    sim = SecureAreaSimulation(
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    sim.run(requests)
    
    # Generate output
    output = sim.get_output(args.test_name)
    
    # Print JSON to stdout
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
