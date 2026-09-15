#!/usr/bin/env python3
"""
Secure Area Access Control with PIN Authentication
Discrete Event Simulation implementation
"""

import argparse
import json
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional
import simpy


class SecureAreaSystem:
    def __init__(self, alarm_admin_delay: float, authentication_delay: float, display_delay: float, max_simulation_time: float):
        self.alarm_admin_delay = alarm_admin_delay
        self.authentication_delay = authentication_delay
        self.display_delay = display_delay
        self.max_simulation_time = max_simulation_time
        
        # System state
        self.state = "Disarmed"
        
        # Events storage
        self.events = []
        self.operations = []
        
        # Simulation environment
        self.env = simpy.Environment()
        
        # Track if admin is busy
        self.admin_busy = False
        self.current_operation = None
        
    def parse_timestamp(self, timestamp_str: str) -> float:
        """Convert HH:MM:SS timestamp to seconds"""
        h, m, s = map(int, timestamp_str.split(':'))
        return h * 3600 + m * 60 + s
    
    def read_input_file(self, input_file_path: str) -> List[Dict[str, Any]]:
        """Read input file and parse requests"""
        requests = []
        try:
            with open(input_file_path, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:  # Skip empty lines
                        continue
                    
                    parts = line.split()
                    if len(parts) != 3:
                        raise ValueError(f"Invalid line {line_num}: {line}")
                    
                    timestamp, port, value = parts
                    if port != '0':
                        raise ValueError(f"Invalid port in line {line_num}: {line}")
                    
                    value = int(value)
                    if value not in [0, 1]:
                        raise ValueError(f"Invalid value in line {line_num}: {line}")
                        
                    requests.append({
                        'timestamp': timestamp,
                        'port': int(port),
                        'value': value,
                        'time': self.parse_timestamp(timestamp)
                    })
        except FileNotFoundError:
            raise FileNotFoundError(f"Input file not found: {input_file_path}")
        except Exception as e:
            raise ValueError(f"Error parsing input file: {str(e)}")
            
        return requests
    
    def input_reader(self, time: float, value: int):
        """Record input reader event"""
        self.events.append({
            'time': time,
            'component': 'input_reader',
            'message': f"{{{time} {value}}}"
        })
        
        # Check if admin is busy
        if self.admin_busy:
            # Ignore the request
            self.operations.append({
                'input_time': time,
                'action': 'disarm' if value == 0 else 'arm',
                'completed': False,
                'completion_time': None
            })
            return
            
        # Accept the request
        self.admin_busy = True
        self.current_operation = {
            'input_time': time,
            'value': value,
            'action': 'disarm' if value == 0 else 'arm'
        }
        
        # Schedule alarm admin event
        self.env.process(self.alarm_admin(time, value))
    
    def alarm_admin(self, input_time: float, value: int):
        """Process alarm admin delay"""
        yield self.env.timeout(self.alarm_admin_delay)
        
        # Emit alarm admin event
        self.events.append({
            'time': input_time + self.alarm_admin_delay,
            'component': 'alarmAdmin',
            'message': f"{{{input_time} {value}}}"
        })
        
        # Schedule authentication
        self.env.process(self.authentication(input_time, value))
    
    def authentication(self, input_time: float, value: int):
        """Process authentication delay"""
        yield self.env.timeout(self.authentication_delay)
        
        # Emit authentication event
        auth_state = "DisarmValid" if value == 0 else "ArmValid"
        self.events.append({
            'time': input_time + self.alarm_admin_delay + self.authentication_delay,
            'component': 'authentication',
            'message': f"{{{input_time} {value}}}",
            'state': auth_state
        })
        
        # Update system state
        if value == 1:  # Arm
            self.state = "Armed"
        else:  # Disarm
            self.state = "Disarmed"
            
        # Schedule display
        self.env.process(self.display(input_time, value))
    
    def display(self, input_time: float, value: int):
        """Process display delay"""
        yield self.env.timeout(self.display_delay)
        
        # Emit display event
        display_state = "Armed" if value == 1 else "Disarmed"
        self.events.append({
            'time': input_time + self.alarm_admin_delay + self.authentication_delay + self.display_delay,
            'component': 'display',
            'message': f"{{{input_time} {value}}}",
            'state': display_state
        })
        
        # Mark operation as completed
        completion_time = input_time + self.alarm_admin_delay + self.authentication_delay
        self.operations.append({
            'input_time': input_time,
            'action': 'disarm' if value == 0 else 'arm',
            'completed': True,
            'completion_time': completion_time
        })
        
        # Admin is now free
        self.admin_busy = False
        self.current_operation = None
    
    def run_simulation(self, input_file_path: str):
        """Run the complete simulation"""
        # Read input requests
        requests = self.read_input_file(input_file_path)
        
        # Sort requests by time
        requests.sort(key=lambda x: x['time'])
        
        # Process each request
        for req in requests:
            self.input_reader(req['time'], req['value'])
        
        # Run simulation until max time or all events processed
        self.env.run(until=self.max_simulation_time)
        
        # Sort events by time
        self.events.sort(key=lambda x: x['time'])
        
        # Determine final state
        final_state = self.state
        
        # Determine simulation time (last event time or max time)
        simulation_time = self.max_simulation_time
        if self.events:
            simulation_time = max(event['time'] for event in self.events)
        
        # Return results
        return {
            'test_name': args.test_name,
            'simulation_time': simulation_time,
            'initial_state': 'Disarmed',
            'final_state': final_state,
            'events': self.events,
            'operations': self.operations
        }


def main():
    parser = argparse.ArgumentParser(description='Secure Area Access Control Simulation')
    parser.add_argument('--test_name', required=True, help='Test name to include in output')
    parser.add_argument('--input_file', help='Input request file path')
    parser.add_argument('--alarm_admin_delay', type=float, default=10.0, help='Alarm admin delay in seconds')
    parser.add_argument('--authentication_delay', type=float, default=2.0, help='Authentication delay in seconds')
    parser.add_argument('--display_delay', type=float, default=3.0, help='Display delay in seconds')
    parser.add_argument('--max_simulation_time', type=float, default=1000.0, help='Maximum simulation time in seconds')
    
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
    try:
        result = system.run_simulation(args.input_file)
        print(json.dumps(result, indent=2), file=sys.stdout)
    except Exception as e:
        print(f"Error: {str(e)}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()