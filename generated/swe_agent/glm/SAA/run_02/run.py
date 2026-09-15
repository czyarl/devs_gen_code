#!/usr/bin/env python3
"""
Secure Area Access Control with PIN Authentication Simulation

This script simulates a secure-area alarm system with an administrator,
an authentication step, and a display using discrete event simulation.
"""

import argparse
import json
import sys
from typing import List, Dict, Any, Optional
import simpy


class AlarmSystemSimulation:
    """Simulates the secure area access control system."""
    
    def __init__(
        self,
        test_name: str,
        alarm_admin_delay: float = 10.0,
        authentication_delay: float = 2.0,
        display_delay: float = 3.0,
        max_simulation_time: float = 1000.0
    ):
        self.test_name = test_name
        self.alarm_admin_delay = alarm_admin_delay
        self.authentication_delay = authentication_delay
        self.display_delay = display_delay
        self.max_simulation_time = max_simulation_time
        
        # System state
        self.state = "Disarmed"
        self.initial_state = "Disarmed"
        
        # Event and operation tracking
        self.events: List[Dict[str, Any]] = []
        self.operations: List[Dict[str, Any]] = []
        
        # Track if AlarmAdmin is busy
        self.alarm_admin_busy = False
        self.alarm_admin_busy_until = 0.0
        
        # Simulation environment
        self.env = simpy.Environment()
        
    def parse_timestamp(self, timestamp_str: str) -> float:
        """Convert HH:MM:SS timestamp to seconds."""
        parts = timestamp_str.split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    
    def parse_input_file(self, input_file: str) -> List[Dict[str, Any]]:
        """Parse the input file and return list of requests."""
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
                time = self.parse_timestamp(timestamp_str)
                requests.append({
                    'time': time,
                    'port': port,
                    'value': value
                })
        return requests
    
    def add_event(self, time: float, component: str, message: str, state: Optional[str] = None):
        """Add an event to the events list."""
        event = {
            'time': time,
            'component': component,
            'message': message
        }
        if state is not None:
            event['state'] = state
        self.events.append(event)
    
    def add_operation(
        self,
        input_time: float,
        action: str,
        completed: bool,
        completion_time: Optional[float]
    ):
        """Add an operation to the operations list."""
        operation = {
            'input_time': input_time,
            'action': action,
            'completed': completed,
            'completion_time': completion_time
        }
        self.operations.append(operation)
    
    def process_request(self, request: Dict[str, Any]):
        """Process a single request through the pipeline."""
        time = request['time']
        port = request['port']
        value = request['value']
        message = f"{{{port} {value}}}"
        
        # Record input_reader event
        self.add_event(time, 'input_reader', message)
        
        # Check if AlarmAdmin is busy
        if self.alarm_admin_busy and time < self.alarm_admin_busy_until:
            # Request is ignored
            action = "disarm" if value == 0 else "arm"
            self.add_operation(time, action, False, None)
            return
        
        # AlarmAdmin accepts the request
        action = "disarm" if value == 0 else "arm"
        self.alarm_admin_busy = True
        
        # AlarmAdmin output at t + alarm_admin_delay
        alarm_admin_time = time + self.alarm_admin_delay
        self.add_event(alarm_admin_time, 'alarmAdmin', message)
        
        # Authentication output at t + alarm_admin_delay + authentication_delay
        auth_time = alarm_admin_time + self.authentication_delay
        auth_state = "DisarmValid" if value == 0 else "ArmValid"
        self.add_event(auth_time, 'authentication', message, auth_state)
        
        # Display output at t + alarm_admin_delay + authentication_delay + display_delay
        display_time = auth_time + self.display_delay
        display_state = "Disarmed" if value == 0 else "Armed"
        self.add_event(display_time, 'display', message, display_state)
        
        # Update system state
        self.state = display_state
        
        # AlarmAdmin stops working at authentication time
        self.alarm_admin_busy_until = auth_time
        
        # Add operation record
        self.add_operation(time, action, True, auth_time)
    
    def run(self, input_file: Optional[str] = None):
        """Run the simulation."""
        # Parse input file if provided
        if input_file:
            requests = self.parse_input_file(input_file)
        else:
            requests = []
        
        # Process requests in order
        for request in requests:
            self.process_request(request)
        
        # Sort events by time
        self.events.sort(key=lambda e: e['time'])
        
        # Sort operations by input_time
        self.operations.sort(key=lambda o: o['input_time'])
        
        # Determine final simulation time
        if self.events:
            last_event_time = max(e['time'] for e in self.events)
            # simulation_time is the time of the last emitted event, or max_simulation_time
            # if the max time is reached before all display events can be produced
            self.simulation_time = min(last_event_time, self.max_simulation_time)
        else:
            self.simulation_time = 0.0
        
        # Final state is the state after the last accepted request
        self.final_state = self.state
    
    def to_json(self) -> Dict[str, Any]:
        """Convert simulation results to JSON format."""
        return {
            'test_name': self.test_name,
            'simulation_time': self.simulation_time,
            'initial_state': self.initial_state,
            'final_state': self.final_state,
            'events': self.events,
            'operations': self.operations
        }


def main():
    """Main entry point for the simulation."""
    parser = argparse.ArgumentParser(
        description='Secure Area Access Control with PIN Authentication Simulation'
    )
    parser.add_argument(
        '--test_name',
        type=str,
        required=True,
        help='Test name copied into the output JSON'
    )
    parser.add_argument(
        '--input_file',
        type=str,
        default=None,
        help='Input request file path'
    )
    parser.add_argument(
        '--alarm_admin_delay',
        type=float,
        default=10.0,
        help='Delay for alarm admin processing (default: 10.0)'
    )
    parser.add_argument(
        '--authentication_delay',
        type=float,
        default=2.0,
        help='Delay for authentication (default: 2.0)'
    )
    parser.add_argument(
        '--display_delay',
        type=float,
        default=3.0,
        help='Delay for display update (default: 3.0)'
    )
    parser.add_argument(
        '--max_simulation_time',
        type=float,
        default=1000.0,
        help='Maximum simulation time (default: 1000.0)'
    )
    
    args = parser.parse_args()
    
    # Create and run simulation
    sim = AlarmSystemSimulation(
        test_name=args.test_name,
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    
    sim.run(input_file=args.input_file)
    
    # Output JSON to stdout
    print(json.dumps(sim.to_json(), indent=2))


if __name__ == '__main__':
    main()