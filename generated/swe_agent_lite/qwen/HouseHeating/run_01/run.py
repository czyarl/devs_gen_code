#!/usr/bin/env python3
"""
House Heating Temperature Control Simulation
"""

import argparse
import sys
import json
from datetime import datetime, timedelta


def parse_time(time_str):
    """Parse HH:MM:SS format to seconds since midnight"""
    h, m, s = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s


def parse_stdin():
    """Parse stdin for outdoor temperature schedule"""
    schedule = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        timestamp_str, temp_str = parts
        try:
            timestamp = parse_time(timestamp_str)
            temperature = float(temp_str)
            schedule.append((timestamp, temperature))
        except ValueError:
            continue
    # Sort by timestamp
    schedule.sort()
    return schedule


def get_outdoor_temp(schedule, time_sec):
    """Get outdoor temperature for given time, using the latest reading <= time_sec"""
    if not schedule:
        return 25.0
    
    # Find the latest reading with timestamp <= time_sec
    temp = 25.0  # Default temperature
    for timestamp, temperature in schedule:
        if timestamp <= time_sec:
            temp = temperature
        else:
            break
    return temp


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulate_time', type=float, required=True,
                       help='Total simulation duration in seconds')
    
    args = parser.parse_args()
    simulate_time = int(args.simulate_time)
    
    # Parse outdoor temperature schedule from stdin
    schedule = parse_stdin()
    
    # Initial state
    room_temp = 25.0
    control_signal = 0
    heater_output = 0.0
    
    # Simulation loop
    for time_sec in range(1, simulate_time + 1):
        # Get outdoor temperature for the previous second
        outdoor_temp = get_outdoor_temp(schedule, time_sec - 1)
        
        # Cap outdoor temperature to room temperature (prevent outdoor heat gain)
        effective_outdoor_temp = min(outdoor_temp, room_temp)
        
        # Calculate heat loss (10% of the difference)
        heat_loss_temp = room_temp - 0.1 * (room_temp - effective_outdoor_temp)
        
        # Apply heater gain from previous control signal
        if control_signal == 1:
            heater_output = 0.5
        else:
            heater_output = 0.0
            
        # Update room temperature
        room_temp = heat_loss_temp + heater_output
        
        # Determine next control signal
        if room_temp < 24.9:
            control_signal = 1
        else:
            control_signal = 0
            
        # Output JSONL record
        output = {
            "time_sec": time_sec,
            "room_temp_c": round(room_temp, 6),
            "heat_loss_temp_c": round(heat_loss_temp, 6),
            "control_signal": control_signal,
            "heater_output_c": round(heater_output, 6)
        }
        print(json.dumps(output))


if __name__ == "__main__":
    main()