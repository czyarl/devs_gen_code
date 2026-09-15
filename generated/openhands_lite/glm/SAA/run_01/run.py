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


class AlarmSystemSimulation:
    """Discrete event simulation for the alarm system."""
    
    def __init__(self, alarm_admin_delay: float, authentication_delay: float, 
                 display_delay: float, max_simulation_time: float):
        self.alarm_admin_delay = alarm_admin_delay
        self.authentication_delay = authentication_delay
        self.display_delay = display_delay
        self.max_simulation_time = max_simulation_time
        
        self.state = "Disarmed"
        self.events: List[Dict[str, Any]] = []
        self.operations: List[Dict[str, Any]] = []
        self.simulation_time = 0.0
        
        # Track if AlarmAdmin is busy
        self.alarm_admin_busy = False
        self.alarm_admin_free_time = 0.0
    
    def run(self, requests: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Run the simulation with given requests."""
        # Sort requests by time
        requests = sorted(requests, key=lambda x: x['time'])
        
        # Process each request
        for request in requests:
            self._process_request(request)
        
        # Calculate final simulation time
        if self.events:
            last_event_time = max(event['time'] for event in self.events)
            if last_event_time <= self.max_simulation_time:
                self.simulation_time = last_event_time
            else:
                self.simulation_time = self.max_simulation_time
        else:
            self.simulation_time = self.max_simulation_time
        
        # Sort events by time
        self.events.sort(key=lambda x: x['time'])
        
        # Sort operations by input_time
        self.operations.sort(key=lambda x: x['input_time'])
        
        return {
            'test_name': None,  # Will be set by main
            'simulation_time': self.simulation_time,
            'initial_state': 'Disarmed',
            'final_state': self.state,
            'events': self.events,
            'operations': self.operations
        }
    
    def _process_request(self, request: Dict[str, Any]):
        """Process a single request through the pipeline."""
        time = request['time']
        port = request['port']
        value = request['value']
        
        # Record input_reader event
        self.events.append({
            'time': time,
            'component': 'input_reader',
            'message': f'{{{port} {value}}}'
        })
        
        # Check if AlarmAdmin is busy
        if self.alarm_admin_busy and time < self.alarm_admin_free_time:
            # Request is ignored
            self.operations.append({
                'input_time': time,
                'action': 'disarm' if value == 0 else 'arm',
                'completed': False,
                'completion_time': None
            })
            return
        
        # AlarmAdmin accepts the request
        self.alarm_admin_busy = True
        
        # Calculate event times
        alarm_admin_time = time + self.alarm_admin_delay
        authentication_time = alarm_admin_time + self.authentication_delay
        display_time = authentication_time + self.display_delay
        
        # Update AlarmAdmin free time
        self.alarm_admin_free_time = authentication_time
        
        # Record alarmAdmin event
        self.events.append({
            'time': alarm_admin_time,
            'component': 'alarmAdmin',
            'message': f'{{{port} {value}}}'
        })
        
        # Record authentication event
        auth_state = 'DisarmValid' if value == 0 else 'ArmValid'
        self.events.append({
            'time': authentication_time,
            'component': 'authentication',
            'message': f'{{{port} {value}}}',
            'state': auth_state
        })
        
        # Update system state
        new_state = 'Disarmed' if value == 0 else 'Armed'
        self.state = new_state
        
        # Record display event
        self.events.append({
            'time': display_time,
            'component': 'display',
            'message': f'{{{port} {value}}}',
            'state': new_state
        })
        
        # Record operation
        self.operations.append({
            'input_time': time,
            'action': 'disarm' if value == 0 else 'arm',
            'completed': True,
            'completion_time': authentication_time
        })


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Secure Area Access Control System Simulation')
    parser.add_argument('--test_name', type=str, required=True,
                        help='Test name for output')
    parser.add_argument('--input_file', type=str, default=None,
                        help='Input request file path')
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
    
    # Run simulation
    sim = AlarmSystemSimulation(
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    
    result = sim.run(requests)
    result['test_name'] = args.test_name
    
    # Output JSON to stdout
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
