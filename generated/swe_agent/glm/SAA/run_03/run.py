#!/usr/bin/env python3
"""
Secure Area Access Control with PIN Authentication
Discrete Event Simulation Implementation
"""

import argparse
import json
import sys
from typing import List, Dict, Any, Optional
import simpy


class AlarmSystemSimulation:
    """Simulates a secure-area alarm system with PIN authentication."""
    
    def __init__(self, test_name: str, alarm_admin_delay: float = 10.0,
                 authentication_delay: float = 2.0, display_delay: float = 3.0,
                 max_simulation_time: float = 1000.0):
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
        
        # Track if AlarmAdmin is working
        self.alarm_admin_busy = False
        self.alarm_admin_busy_until = 0.0
        
        # Track input requests
        self.input_requests: List[Dict[str, Any]] = []
        
    def parse_timestamp(self, timestamp_str: str) -> float:
        """Convert HH:MM:SS timestamp to seconds."""
        parts = timestamp_str.split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        return hours * 3600 + minutes * 60 + seconds
    
    def parse_input_file(self, input_file: str):
        """Parse input file with timestamp, port, and value."""
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
                self.input_requests.append({
                    'time': time,
                    'port': port,
                    'value': value
                })
        
        # Sort by time
        self.input_requests.sort(key=lambda x: x['time'])
    
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
    
    def add_operation(self, input_time: float, action: str, completed: bool,
                     completion_time: Optional[float]):
        """Add an operation to the operations list."""
        operation = {
            'input_time': input_time,
            'action': action,
            'completed': completed,
            'completion_time': completion_time
        }
        self.operations.append(operation)
    
    def run_simulation(self):
        """Run the discrete event simulation."""
        # Process each input request
        for request in self.input_requests:
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
            else:
                # Request is accepted
                action = "disarm" if value == 0 else "arm"
                
                # AlarmAdmin event
                alarm_admin_time = time + self.alarm_admin_delay
                
                # Check if alarm_admin_time exceeds max_simulation_time
                if alarm_admin_time > self.max_simulation_time:
                    # Request is ignored due to max_simulation_time
                    self.add_operation(time, action, False, None)
                    continue
                
                self.add_event(alarm_admin_time, 'alarmAdmin', message)
                
                # Authentication event
                auth_time = alarm_admin_time + self.authentication_delay
                
                # Check if auth_time exceeds max_simulation_time
                if auth_time > self.max_simulation_time:
                    # Request is ignored due to max_simulation_time
                    self.add_operation(time, action, False, None)
                    continue
                
                auth_state = "DisarmValid" if value == 0 else "ArmValid"
                self.add_event(auth_time, 'authentication', message, auth_state)
                
                # Display event
                display_time = auth_time + self.display_delay
                
                # Check if display_time exceeds max_simulation_time
                if display_time > self.max_simulation_time:
                    # Request is ignored due to max_simulation_time
                    self.add_operation(time, action, False, None)
                    continue
                
                display_state = "Disarmed" if value == 0 else "Armed"
                self.add_event(display_time, 'display', message, display_state)
                
                # Update system state
                self.state = display_state
                
                # Mark AlarmAdmin as busy until authentication completes
                self.alarm_admin_busy = True
                self.alarm_admin_busy_until = auth_time
                
                # Record operation
                self.add_operation(time, action, True, auth_time)
        
        # Sort events by time
        self.events.sort(key=lambda x: x['time'])
        
        # Sort operations by input_time
        self.operations.sort(key=lambda x: x['input_time'])
        
        # Calculate simulation time
        if self.events:
            self.simulation_time = self.events[-1]['time']
        else:
            self.simulation_time = 0.0
    
    def get_output(self) -> Dict[str, Any]:
        """Get the output JSON object."""
        return {
            'test_name': self.test_name,
            'simulation_time': self.simulation_time,
            'initial_state': self.initial_state,
            'final_state': self.state,
            'events': self.events,
            'operations': self.operations
        }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Secure Area Access Control with PIN Authentication Simulation'
    )
    parser.add_argument('--test_name', type=str, required=True,
                       help='Test name copied into output JSON')
    parser.add_argument('--input_file', type=str, default=None,
                       help='Input request file path')
    parser.add_argument('--alarm_admin_delay', type=float, default=10.0,
                       help='Alarm admin delay in seconds (default: 10.0)')
    parser.add_argument('--authentication_delay', type=float, default=2.0,
                       help='Authentication delay in seconds (default: 2.0)')
    parser.add_argument('--display_delay', type=float, default=3.0,
                       help='Display delay in seconds (default: 3.0)')
    parser.add_argument('--max_simulation_time', type=float, default=1000.0,
                       help='Maximum simulation time in seconds (default: 1000.0)')
    
    args = parser.parse_args()
    
    # Create simulation
    sim = AlarmSystemSimulation(
        test_name=args.test_name,
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    
    # Parse input file if provided
    if args.input_file:
        sim.parse_input_file(args.input_file)
    
    # Run simulation
    sim.run_simulation()
    
    # Output JSON to stdout
    output = sim.get_output()
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
