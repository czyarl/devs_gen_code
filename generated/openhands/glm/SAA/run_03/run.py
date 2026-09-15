#!/usr/bin/env python3
"""
Secure Area Access Control System - Discrete Event Simulation
"""

import argparse
import json
import sys
from typing import List, Dict, Any, Optional
import simpy


class SecureAreaAccessControl:
    """Simulates a secure-area alarm system with PIN authentication."""
    
    def __init__(
        self,
        alarm_admin_delay: float = 10.0,
        authentication_delay: float = 2.0,
        display_delay: float = 3.0,
        max_simulation_time: float = 1000.0
    ):
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
        
        # AlarmAdmin busy flag
        self.alarm_admin_busy = False
        self.alarm_admin_busy_until = 0.0
    
    def parse_timestamp(self, timestamp_str: str) -> float:
        """Convert HH:MM:SS timestamp to seconds."""
        parts = timestamp_str.split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    
    def parse_input_file(self, input_file: str) -> List[Dict[str, Any]]:
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
    
    def process_request(self, env: simpy.Environment, request: Dict[str, Any]):
        """Process a single request through the pipeline."""
        time = request['time']
        port = request['port']
        value = request['value']
        
        # Record input_reader event
        message = f"{{{port} {value}}}"
        self.add_event(time, 'input_reader', message)
        
        # Check if AlarmAdmin is busy (busy until previous authentication completes)
        if self.alarm_admin_busy and time < self.alarm_admin_busy_until:
            # Request is ignored
            action = "disarm" if value == 0 else "arm"
            self.operations.append({
                'input_time': time,
                'action': action,
                'completed': False,
                'completion_time': None
            })
            return
        
        # AlarmAdmin accepts the request
        self.alarm_admin_busy = True
        
        # Calculate completion times
        alarm_admin_time = time + self.alarm_admin_delay
        auth_time = alarm_admin_time + self.authentication_delay
        display_time = auth_time + self.display_delay
        
        # Set when AlarmAdmin will be free (at authentication time)
        self.alarm_admin_busy_until = auth_time
        
        # AlarmAdmin output
        yield env.timeout(alarm_admin_time - env.now)
        self.add_event(alarm_admin_time, 'alarmAdmin', message)
        
        # Authentication output
        yield env.timeout(auth_time - env.now)
        auth_state = "DisarmValid" if value == 0 else "ArmValid"
        self.add_event(auth_time, 'authentication', message, state=auth_state)
        
        # Display output
        yield env.timeout(display_time - env.now)
        display_state = "Disarmed" if value == 0 else "Armed"
        self.add_event(display_time, 'display', message, state=display_state)
        
        # Update system state
        self.state = display_state
        
        # AlarmAdmin is no longer busy
        self.alarm_admin_busy = False
        
        # Record operation
        action = "disarm" if value == 0 else "arm"
        self.operations.append({
            'input_time': time,
            'action': action,
            'completed': True,
            'completion_time': auth_time
        })
    
    def run_simulation(self, test_name: str, input_file: Optional[str] = None):
        """Run the discrete event simulation."""
        env = simpy.Environment()
        
        # Parse input file if provided
        requests = []
        if input_file:
            requests = self.parse_input_file(input_file)
        
        # Sort requests by time
        requests.sort(key=lambda x: x['time'])
        
        # Schedule all requests
        for request in requests:
            env.process(self.process_request(env, request))
        
        # Run simulation
        env.run(until=self.max_simulation_time)
        
        # Sort events by time
        self.events.sort(key=lambda x: x['time'])
        
        # Sort operations by input_time
        self.operations.sort(key=lambda x: x['input_time'])
        
        # Determine simulation time
        if self.events:
            simulation_time = max(event['time'] for event in self.events)
        else:
            simulation_time = 0.0
        
        # Build output
        output = {
            'test_name': test_name,
            'simulation_time': simulation_time,
            'initial_state': self.initial_state,
            'final_state': self.state,
            'events': self.events,
            'operations': self.operations
        }
        
        return output


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Secure Area Access Control System Simulation'
    )
    parser.add_argument(
        '--test_name',
        type=str,
        required=True,
        help='Test name for output'
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
        help='Alarm admin delay in seconds'
    )
    parser.add_argument(
        '--authentication_delay',
        type=float,
        default=2.0,
        help='Authentication delay in seconds'
    )
    parser.add_argument(
        '--display_delay',
        type=float,
        default=3.0,
        help='Display delay in seconds'
    )
    parser.add_argument(
        '--max_simulation_time',
        type=float,
        default=1000.0,
        help='Maximum simulation time in seconds'
    )
    
    args = parser.parse_args()
    
    # Create and run simulation
    sim = SecureAreaAccessControl(
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    
    output = sim.run_simulation(
        test_name=args.test_name,
        input_file=args.input_file
    )
    
    # Print output to stdout
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
