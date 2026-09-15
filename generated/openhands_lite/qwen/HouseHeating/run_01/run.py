#!/usr/bin/env python3
"""
House Heating Temperature Control Simulation
"""

import argparse
import json
import sys
from datetime import datetime


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
        timestamp, temp = parts
        schedule.append((parse_time(timestamp), float(temp)))
    return sorted(schedule)


def get_outdoor_temp(schedule, time_sec):
    """Get outdoor temperature for given time, using the latest reading <= time_sec"""
    # Find the latest reading with timestamp <= time_sec
    temp = 25.0  # Default temperature
    for timestamp, temp_value in reversed(schedule):
        if timestamp <= time_sec:
            temp = temp_value
            break
    return temp


def main():
    parser = argparse.ArgumentParser(description='House Heating Temperature Control Simulation')
    parser.add_argument('--simulate_time', type=float, required=True, help='Total simulation duration in seconds')
    
    args = parser.parse_args()
    
    # Parse outdoor temperature schedule from stdin
    schedule = parse_stdin()
    
    # Simulation parameters
    simulate_time = int(args.simulate_time)
    
    # Initial state
    room_temp = 25.0
    control_signal = 0
    heater_output = 0.0
    
    # Store previous values for heater delay
    prev_control_signal = 0
    
    # Output JSONL records
    for time_sec in range(1, simulate_time + 1):
        # Get outdoor temperature for this time step
        outdoor_temp = get_outdoor_temp(schedule, time_sec)
        
        # Apply heat loss: cap outdoor temp to room temp to prevent heat gain
        effective_outdoor_temp = min(outdoor_temp, room_temp)
        
        # Calculate heat loss (10% of the difference)
        heat_loss_temp = room_temp - 0.1 * (room_temp - effective_outdoor_temp)
        
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
        
        # Update previous control signal for next iteration
        prev_control_signal = control_signal


if __name__ == "__main__":
    main()