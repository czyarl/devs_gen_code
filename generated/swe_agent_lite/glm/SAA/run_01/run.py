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


def simulate(
    requests: List[Dict[str, Any]],
    alarm_admin_delay: float,
    authentication_delay: float,
    display_delay: float,
    max_simulation_time: float
) -> Dict[str, Any]:
    """
    Run the discrete event simulation.
    
    Returns a dictionary with simulation results including events and operations.
    """
    # System state
    current_state = "Disarmed"
    initial_state = "Disarmed"
    
    # Track if AlarmAdmin is working
    alarm_admin_busy = False
    alarm_admin_free_time = 0.0
    
    # Event queue: list of (time, component, message, state)
    events: List[Dict[str, Any]] = []
    
    # Operation records
    operations: List[Dict[str, Any]] = []
    
    # Process each input request
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
        if alarm_admin_busy and input_time < alarm_admin_free_time:
            # Request is ignored
            operations.append({
                'input_time': input_time,
                'action': 'disarm' if value == 0 else 'arm',
                'completed': False,
                'completion_time': None
            })
            continue
        
        # AlarmAdmin accepts the request
        alarm_admin_busy = True
        
        # Calculate event times
        alarm_admin_time = input_time + alarm_admin_delay
        auth_time = alarm_admin_time + authentication_delay
        display_time = auth_time + display_delay
        
        # AlarmAdmin becomes free at auth_time
        alarm_admin_free_time = auth_time
        
        # Record alarmAdmin event
        events.append({
            'time': alarm_admin_time,
            'component': 'alarmAdmin',
            'message': f'{{{port} {value}}}'
        })
        
        # Record authentication event
        auth_state = "DisarmValid" if value == 0 else "ArmValid"
        events.append({
            'time': auth_time,
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
            'completion_time': auth_time
        })
        
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
        'simulation_time': simulation_time,
        'events': events,
        'operations': operations
    }


def main():
    parser = argparse.ArgumentParser(
        description='Secure Area Access Control with PIN Authentication Simulation'
    )
    parser.add_argument(
        '--test_name',
        type=str,
        required=True,
        help='Test name copied into output JSON'
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
        help='Alarm admin delay in seconds (default: 10.0)'
    )
    parser.add_argument(
        '--authentication_delay',
        type=float,
        default=2.0,
        help='Authentication delay in seconds (default: 2.0)'
    )
    parser.add_argument(
        '--display_delay',
        type=float,
        default=3.0,
        help='Display delay in seconds (default: 3.0)'
    )
    parser.add_argument(
        '--max_simulation_time',
        type=float,
        default=1000.0,
        help='Maximum simulation time in seconds (default: 1000.0)'
    )
    
    args = parser.parse_args()
    
    # Parse input file if provided
    requests = []
    if args.input_file:
        requests = parse_input_file(args.input_file)
    
    # Run simulation
    result = simulate(
        requests=requests,
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    
    # Build output JSON
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