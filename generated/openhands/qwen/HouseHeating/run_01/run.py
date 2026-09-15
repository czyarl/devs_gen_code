#!/usr/bin/env python3
"""
House Heating Temperature Control Simulation
"""

import argparse
import json
import sys
from datetime import datetime, timedelta


def parse_time(time_str):
    """Parse HH:MM:SS format to seconds since midnight"""
    h, m, s = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s


def parse_outdoor_schedule():
    """Parse outdoor temperature schedule from stdin"""
    schedule = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        time_str, temp_str = parts
        try:
            timestamp = parse_time(time_str)
            temperature = float(temp_str)
            schedule.append((timestamp, temperature))
        except ValueError:
            continue
    return sorted(schedule)


def get_outdoor_temperature(schedule, time_sec):
    """Get outdoor temperature for given time, using the latest reading <= time_sec"""
    # Find the latest reading with timestamp <= time_sec
    temp_at_time = 25.0  # Default temperature
    for timestamp, temperature in reversed(schedule):
        if timestamp <= time_sec:
            temp_at_time = temperature
            break
    
    return temp_at_time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulate_time', type=float, required=True,
                       help='Total simulation duration in seconds')
    
    args = parser.parse_args()
    
    # Parse outdoor temperature schedule
    schedule = parse_outdoor_schedule()
    
    # Simulation parameters
    simulate_time = int(args.simulate_time)
    
    # Initial state
    room_temp = 25.0
    prev_control_signal = 0
    prev_room_temp = 25.0
    
    # Process each time step
    for time_sec in range(1, simulate_time + 1):
        # Get outdoor temperature for the previous second
        outdoor_temp = get_outdoor_temperature(schedule, time_sec - 1)
        
        # Cap outdoor temperature to room temperature to prevent heat gain
        effective_outdoor_temp = min(outdoor_temp, prev_room_temp)
        
        # Calculate heat loss (10% of the difference)
        heat_loss_temp = prev_room_temp - 0.1 * (prev_room_temp - effective_outdoor_temp)
        
        # Apply heater gain (delayed by one step)
        heater_output = 0.5 if prev_control_signal == 1 else 0.0
        
        # Calculate new room temperature
        room_temp = heat_loss_temp + heater_output
        
        # Determine control signal for next step
        control_signal = 1 if room_temp < 24.9 else 0
        
        # Output JSONL record
        output = {
            "time_sec": time_sec,
            "room_temp_c": round(room_temp, 6),
            "heat_loss_temp_c": round(heat_loss_temp, 6),
            "control_signal": control_signal,
            "heater_output_c": heater_output
        }
        
        print(json.dumps(output))
        
        # Update state for next iteration
        prev_room_temp = room_temp
        prev_control_signal = control_signal


if __name__ == "__main__":
    main()