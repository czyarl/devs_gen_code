#!/usr/bin/env python3
"""
House Heating Temperature Control Simulation
"""

import argparse
import sys
import json


def parse_time(time_str):
    """Parse HH:MM:SS format to seconds since midnight."""
    h, m, s = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s


def parse_stdin():
    """Parse stdin for outdoor temperature schedule."""
    schedule = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        timestamp_str, temp_str = parts
        timestamp = parse_time(timestamp_str)
        temperature = float(temp_str)
        schedule.append((timestamp, temperature))
    return sorted(schedule)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulate_time', type=float, required=True,
                       help='Total simulation duration in seconds')
    
    args = parser.parse_args()
    simulate_time = int(args.simulate_time)
    
    # Parse outdoor temperature schedule
    schedule = parse_stdin()
    
    # Initial state
    room_temp = 25.0
    control_signal = 0
    heater_output = 0.0
    
    # Previous state for heater delay
    prev_control_signal = 0
    
    # Process each time step
    for t in range(1, simulate_time + 1):
        # Find the effective outdoor temperature for this time step
        # Use the reading with greatest timestamp <= t
        effective_outdoor_temp = 25.0  # default if no reading found
        for timestamp, temp in schedule:
            if timestamp <= t:
                effective_outdoor_temp = temp
            else:
                break
        
        # Cap outdoor temperature to room temperature (prevent outdoor heat gain)
        effective_outdoor_temp = min(effective_outdoor_temp, room_temp)
        
        # Calculate heat loss: 10% of the gap between room and outdoor temperature
        heat_loss_temp = room_temp - 0.1 * (room_temp - effective_outdoor_temp)
        
        # Apply heater gain (delayed by one step)
        # Heater adds 0.5°C if previous control signal was 1, otherwise 0.0°C
        heater_output = 0.5 if prev_control_signal == 1 else 0.0
        
        # Calculate new room temperature
        room_temp = heat_loss_temp + heater_output
        
        # Determine next control signal
        # Turn heater on if room temperature is below 24.9°C
        control_signal = 1 if room_temp < 24.9 else 0
        
        # Output JSONL record
        output = {
            "time_sec": t,
            "room_temp_c": round(room_temp, 6),
            "heat_loss_temp_c": round(heat_loss_temp, 6),
            "control_signal": control_signal,
            "heater_output_c": round(heater_output, 6)
        }
        print(json.dumps(output))
        
        # Update previous control signal for next iteration
        prev_control_signal = control_signal


if __name__ == '__main__':
    main()