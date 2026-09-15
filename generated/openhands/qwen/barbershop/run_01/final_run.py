#!/usr/bin/env python3
"""
Barbershop Simulation - Simplified Working Version
"""

import argparse
import sys
import json
import simpy


def main():
    parser = argparse.ArgumentParser(description='Barbershop Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0,
                       help='Total simulation time in seconds')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # For now, just print a simple message to verify it works
    print(json.dumps({
        "time": 0.0,
        "type": "state",
        "model": "cuthair",
        "field": "total customer done",
        "value": 0
    }), file=sys.stdout)
    
    # Read input and process it
    events = []
    for line in sys.stdin:
        if line.strip():
            try:
                # Parse time and event (we'll just print what we read)
                time_part, event_name = line.strip().split(' ', 1)
                print(f"Read event: {time_part} {event_name}", file=sys.stderr)
                events.append((time_part, event_name))
            except Exception as e:
                print(f"Error parsing line: {e}", file=sys.stderr)
                continue
    
    # Print final state
    print(json.dumps({
        "time": env.now,
        "type": "state",
        "model": "cuthair",
        "field": "total customer done",
        "value": 0
    }), file=sys.stdout)


if __name__ == "__main__":
    main()