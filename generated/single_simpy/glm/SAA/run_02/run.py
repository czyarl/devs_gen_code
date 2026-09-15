#!/usr/bin/env python3
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
    """Parse the input file and return list of requests sorted by time."""
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
    # Sort requests by time for chronological processing
    requests.sort(key=lambda r: r['time'])
    return requests


def simulate(
    requests: List[Dict[str, Any]],
    alarm_admin_delay: float,
    authentication_delay: float,
    display_delay: float,
    max_simulation_time: float
) -> Dict[str, Any]:
    """Run the simulation and return results."""
    
    initial_state = "Disarmed"
    current_state = initial_state
    
    events: List[Dict[str, Any]] = []
    operations: List[Dict[str, Any]] = []
    
    # Track when AlarmAdmin becomes free (authentication completion time)
    admin_free_time = 0.0
    
    # Track if all display events can be produced within max_simulation_time
    all_display_produced = True
    
    # Process requests in chronological order
    for req in requests:
        input_time = req['time']
        port = req['port']
        value = req['value']
        
        # Stop processing if input time exceeds max simulation time
        if input_time > max_simulation_time:
            break
        
        # Record input_reader event for every input line
        events.append({
            'time': input_time,
            'component': 'input_reader',
            'message': f'{{{port} {value}}}'
        })
        
        # Check if AlarmAdmin is busy working on a previous request
        completed = False
        completion_time = None
        
        if input_time >= admin_free_time:
            # Request is accepted - AlarmAdmin is free
            completed = True
            
            # AlarmAdmin event after alarm_admin_delay
            alarm_admin_time = input_time + alarm_admin_delay
            if alarm_admin_time <= max_simulation_time:
                events.append({
                    'time': alarm_admin_time,
                    'component': 'alarmAdmin',
                    'message': f'{{{port} {value}}}'
                })
            
            # Authentication event after authentication_delay
            auth_time = input_time + alarm_admin_delay + authentication_delay
            auth_state = "DisarmValid" if value == 0 else "ArmValid"
            if auth_time <= max_simulation_time:
                events.append({
                    'time': auth_time,
                    'component': 'authentication',
                    'message': f'{{{port} {value}}}',
                    'state': auth_state
                })
            
            # Display event after display_delay
            display_time = input_time + alarm_admin_delay + authentication_delay + display_delay
            display_state = "Disarmed" if value == 0 else "Armed"
            if display_time <= max_simulation_time:
                events.append({
                    'time': display_time,
                    'component': 'display',
                    'message': f'{{{port} {value}}}',
                    'state': display_state
                })
            
            # Check if display event can be produced within max time
            if display_time > max_simulation_time:
                all_display_produced = False
            
            # Update system state based on the accepted request
            current_state = display_state
            
            # Update admin_free_time to when authentication completes
            admin_free_time = auth_time
            completion_time = auth_time
        
        # Record operation for this input request
        action = "disarm" if value == 0 else "arm"
        operations.append({
            'input_time': input_time,
            'action': action,
            'completed': completed,
            'completion_time': completion_time
        })
    
    # Sort events by nondecreasing simulation time
    events.sort(key=lambda e: e['time'])
    
    # Sort operations by input_time
    operations.sort(key=lambda op: op['input_time'])
    
    # Determine final simulation time
    # Normally the time of the last emitted event after all accepted display events are produced
    # Or max_simulation_time if max time is reached before all display events can be produced
    if all_display_produced:
        if events:
            simulation_time = events[-1]['time']
        else:
            simulation_time = 0.0
    else:
        simulation_time = max_simulation_time
    
    return {
        'simulation_time': simulation_time,
        'initial_state': initial_state,
        'final_state': current_state,
        'events': events,
        'operations': operations
    }


def main():
    parser = argparse.ArgumentParser(description='Secure Area Access Control Simulation')
    parser.add_argument('--test_name', type=str, required=True, help='Test name')
    parser.add_argument('--input_file', type=str, help='Input request file path')
    parser.add_argument('--alarm_admin_delay', type=float, default=10.0, help='Alarm admin delay')
    parser.add_argument('--authentication_delay', type=float, default=2.0, help='Authentication delay')
    parser.add_argument('--display_delay', type=float, default=3.0, help='Display delay')
    parser.add_argument('--max_simulation_time', type=float, default=1000.0, help='Max simulation time')
    
    args = parser.parse_args()
    
    # Parse input file if provided
    requests = []
    if args.input_file:
        requests = parse_input_file(args.input_file)
    
    # Run simulation
    result = simulate(
        requests,
        args.alarm_admin_delay,
        args.authentication_delay,
        args.display_delay,
        args.max_simulation_time
    )
    
    # Add test_name to result
    result['test_name'] = args.test_name
    
    # Output JSON to stdout
    print(json.dumps(result, indent=2))
    
    # Debug info to stderr
    print(f"Simulation completed. Events: {len(result['events'])}, Operations: {len(result['operations'])}", file=sys.stderr)


if __name__ == '__main__':
    main()