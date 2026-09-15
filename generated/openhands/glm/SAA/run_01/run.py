#!/usr/bin/env python3
"""
Secure Area Access Control with PIN Authentication - Discrete Event Simulation
"""

import argparse
import json
import sys
from typing import List, Dict, Any, Optional


def parse_timestamp(timestamp_str: str) -> float:
    """Convert HH:MM:SS timestamp to seconds."""
    parts = timestamp_str.split(':')
    hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
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


def simulate(
    requests: List[Dict[str, Any]],
    alarm_admin_delay: float,
    authentication_delay: float,
    display_delay: float,
    max_simulation_time: float
) -> Dict[str, Any]:
    """Run discrete event simulation."""
    
    # Initialize state
    current_state = "Disarmed"
    initial_state = current_state
    
    # Events and operations tracking
    events: List[Dict[str, Any]] = []
    operations: List[Dict[str, Any]] = []
    
    # Track when AlarmAdmin becomes available
    alarm_admin_available_until = 0.0
    
    # Process each request
    for req in requests:
        input_time = req['time']
        port = req['port']
        value = req['value']
        
        # Record input_reader event
        events.append({
            'time': input_time,
            'component': 'input_reader',
            'message': f'{{{port} {value}}}'
        })
        
        # Check if AlarmAdmin is busy
        if input_time < alarm_admin_available_until:
            # Request is ignored
            operations.append({
                'input_time': input_time,
                'action': 'disarm' if value == 0 else 'arm',
                'completed': False,
                'completion_time': None
            })
            continue
        
        # Request is accepted
        alarm_admin_time = input_time + alarm_admin_delay
        authentication_time = alarm_admin_time + authentication_delay
        display_time = authentication_time + display_delay
        
        # Record alarmAdmin event
        events.append({
            'time': alarm_admin_time,
            'component': 'alarmAdmin',
            'message': f'{{{port} {value}}}'
        })
        
        # Record authentication event
        auth_state = "DisarmValid" if value == 0 else "ArmValid"
        events.append({
            'time': authentication_time,
            'component': 'authentication',
            'message': f'{{{port} {value}}}',
            'state': auth_state
        })
        
        # Update system state
        current_state = "Disarmed" if value == 0 else "Armed"
        
        # Record display event
        display_state = "Disarmed" if value == 0 else "Armed"
        events.append({
            'time': display_time,
            'component': 'display',
            'message': f'{{{port} {value}}}',
            'state': display_state
        })
        
        # Record operation
        operations.append({
            'input_time': input_time,
            'action': 'disarm' if value == 0 else 'arm',
            'completed': True,
            'completion_time': authentication_time
        })
        
        # Update AlarmAdmin availability
        alarm_admin_available_until = authentication_time
        
        # Check if we've exceeded max simulation time
        if display_time > max_simulation_time:
            break
    
    # Sort events by time
    events.sort(key=lambda e: e['time'])
    
    # Sort operations by input_time
    operations.sort(key=lambda o: o['input_time'])
    
    # Determine final simulation time
    if events:
        simulation_time = min(events[-1]['time'], max_simulation_time)
    else:
        simulation_time = 0.0
    
    return {
        'initial_state': initial_state,
        'final_state': current_state,
        'events': events,
        'operations': operations,
        'simulation_time': simulation_time
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Secure Area Access Control with PIN Authentication Simulation'
    )
    parser.add_argument('--test_name', type=str, required=True,
                        help='Test name copied into output JSON')
    parser.add_argument('--input_file', type=str, required=True,
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
    
    # Parse input file
    requests = parse_input_file(args.input_file)
    
    # Run simulation
    result = simulate(
        requests=requests,
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    
    # Build output
    output = {
        'test_name': args.test_name,
        'simulation_time': result['simulation_time'],
        'initial_state': result['initial_state'],
        'final_state': result['final_state'],
        'events': result['events'],
        'operations': result['operations']
    }
    
    # Print JSON to stdout
    print(json.dumps(output, indent=2))


if __name__ == '__main__':
    main()
