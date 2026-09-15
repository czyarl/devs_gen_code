#!/usr/bin/env python3
"""
Secure Area Access Control with PIN Authentication - Discrete Event Simulation

This script simulates a secure-area alarm system with an administrator,
authentication step, and display using discrete event simulation.
"""

import argparse
import json
import sys
from typing import List, Dict, Any, Optional


def parse_timestamp(timestamp_str: str) -> float:
    """
    Convert HH:MM:SS timestamp to seconds.
    
    Args:
        timestamp_str: Timestamp in HH:MM:SS format
        
    Returns:
        Time in seconds as a float
    """
    parts = timestamp_str.strip().split(':')
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp format: {timestamp_str}")
    
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    
    return hours * 3600 + minutes * 60 + seconds


def parse_input_file(input_file_path: str) -> List[Dict[str, Any]]:
    """
    Parse the input file containing operation requests.
    
    Args:
        input_file_path: Path to the input file
        
    Returns:
        List of parsed input requests with time, port, and value
    """
    requests = []
    
    try:
        with open(input_file_path, 'r') as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                
                # Skip blank lines
                if not line:
                    continue
                
                parts = line.split()
                if len(parts) != 3:
                    print(f"Warning: Invalid line {line_num}: '{line}'", file=sys.stderr)
                    continue
                
                timestamp_str = parts[0]
                port = int(parts[1])
                value = int(parts[2])
                
                time = parse_timestamp(timestamp_str)
                
                requests.append({
                    'time': time,
                    'port': port,
                    'value': value,
                    'line': line
                })
    except FileNotFoundError:
        print(f"Error: Input file not found: {input_file_path}", file=sys.stderr)
        sys.exit(1)
    
    return requests


class Event:
    """Represents a discrete event in the simulation."""
    
    def __init__(self, time: float, component: str, message: str, state: Optional[str] = None):
        self.time = time
        self.component = component
        self.message = message
        self.state = state
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary for JSON output."""
        result = {
            'time': self.time,
            'component': self.component,
            'message': self.message
        }
        if self.state is not None:
            result['state'] = self.state
        return result
    
    def __lt__(self, other):
        return self.time < other.time


class Simulation:
    """
    Discrete event simulation for the secure area access control system.
    """
    
    def __init__(self, 
                 alarm_admin_delay: float,
                 authentication_delay: float,
                 display_delay: float,
                 max_simulation_time: float):
        self.alarm_admin_delay = alarm_admin_delay
        self.authentication_delay = authentication_delay
        self.display_delay = display_delay
        self.max_simulation_time = max_simulation_time
        
        # System state
        self.current_state = "Disarmed"
        self.alarm_admin_busy = False
        self.alarm_admin_free_time = 0.0
        
        # Records
        self.events: List[Event] = []
        self.operations: List[Dict[str, Any]] = []
        
        # Simulation time
        self.simulation_time = 0.0
    
    def add_event(self, time: float, component: str, message: str, state: Optional[str] = None):
        """Add an event to the simulation."""
        event = Event(time, component, message, state)
        self.events.append(event)
    
    def process_request(self, request: Dict[str, Any]) -> bool:
        """
        Process a single input request.
        
        Args:
            request: Dictionary with time, port, value, and line
            
        Returns:
            True if request was accepted, False if ignored
        """
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
        
        # Accept the request
        action = "disarm" if value == 0 else "arm"
        
        # AlarmAdmin outputs at t + alarm_admin_delay
        alarm_admin_time = time + self.alarm_admin_delay
        self.add_event(alarm_admin_time, 'alarmAdmin', message)
        
        # Authentication outputs at t + alarm_admin_delay + authentication_delay
        auth_time = time + self.alarm_admin_delay + self.authentication_delay
        auth_state = "DisarmValid" if value == 0 else "ArmValid"
        self.add_event(auth_time, 'authentication', message, auth_state)
        
        # Display outputs at t + alarm_admin_delay + authentication_delay + display_delay
        display_time = time + self.alarm_admin_delay + self.authentication_delay + self.display_delay
        display_state = "Disarmed" if value == 0 else "Armed"
        self.add_event(display_time, 'display', message, display_state)
        
        # Update system state
        self.current_state = display_state
        
        # Mark AlarmAdmin as busy until authentication completes
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
        """
        Run the simulation with the given requests.
        
        Args:
            requests: List of parsed input requests
        """
        # Sort requests by time
        requests.sort(key=lambda r: r['time'])
        
        # Process each request
        for request in requests:
            # Check if we've exceeded max simulation time
            if request['time'] > self.max_simulation_time:
                print(f"Warning: Request at time {request['time']} exceeds max_simulation_time {self.max_simulation_time}", 
                      file=sys.stderr)
                break
            
            # Process the request
            self.process_request(request)
        
        # Determine final simulation time
        if self.events:
            # Simulation time is the time of the last emitted event
            self.simulation_time = max(event.time for event in self.events)
            
            # But if max_simulation_time is reached before all events, use max_simulation_time
            if self.simulation_time > self.max_simulation_time:
                self.simulation_time = self.max_simulation_time
        else:
            self.simulation_time = 0.0
    
    def get_output(self, test_name: str) -> Dict[str, Any]:
        """
        Generate the output JSON object.
        
        Args:
            test_name: Name of the test
            
        Returns:
            Dictionary with all required output fields
        """
        # Sort events by time
        self.events.sort(key=lambda e: e.time)
        
        # Sort operations by input_time
        self.operations.sort(key=lambda op: op['input_time'])
        
        return {
            'test_name': test_name,
            'simulation_time': self.simulation_time,
            'initial_state': 'Disarmed',
            'final_state': self.current_state,
            'events': [event.to_dict() for event in self.events],
            'operations': self.operations
        }


def main():
    """Main entry point for the simulation."""
    parser = argparse.ArgumentParser(
        description='Secure Area Access Control with PIN Authentication - Discrete Event Simulation'
    )
    
    parser.add_argument(
        '--test_name',
        type=str,
        required=True,
        help='Name of the test (copied into output JSON)'
    )
    
    parser.add_argument(
        '--input_file',
        type=str,
        help='Input request file path'
    )
    
    parser.add_argument(
        '--alarm_admin_delay',
        type=float,
        default=10.0,
        help='Delay for AlarmAdmin component (default: 10.0)'
    )
    
    parser.add_argument(
        '--authentication_delay',
        type=float,
        default=2.0,
        help='Delay for Authentication component (default: 2.0)'
    )
    
    parser.add_argument(
        '--display_delay',
        type=float,
        default=3.0,
        help='Delay for Display component (default: 3.0)'
    )
    
    parser.add_argument(
        '--max_simulation_time',
        type=float,
        default=1000.0,
        help='Maximum simulation time (default: 1000.0)'
    )
    
    args = parser.parse_args()
    
    # Parse input file if provided
    if args.input_file:
        requests = parse_input_file(args.input_file)
    else:
        requests = []
    
    # Create and run simulation
    sim = Simulation(
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    
    sim.run(requests)
    
    # Generate and print output
    output = sim.get_output(args.test_name)
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
