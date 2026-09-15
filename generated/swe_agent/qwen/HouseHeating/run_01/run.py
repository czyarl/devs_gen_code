#!/usr/bin/env python3
"""
House Heating Temperature Control Simulation
"""

import argparse
import sys
import json

def parse_time(time_str):
    """Parse HH:MM:SS format to seconds since midnight"""
    h, m, s = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulate_time', type=float, required=True,
                       help='Total simulation duration in seconds')
    
    args = parser.parse_args()
    
    # Read outdoor temperature schedule from stdin
    outdoor_temps = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        try:
            timestamp = parts[0]
            temp = float(parts[1])
            outdoor_temps.append((parse_time(timestamp), temp))
        except ValueError:
            # Skip malformed lines
            continue
    
    # Sort outdoor temperatures by time
    outdoor_temps.sort()
    
    # Simulation parameters
    simulate_time = int(args.simulate_time)
    
    # Initial state
    room_temp = 25.0
    control_signal = 0
    heater_output = 0.0
    
    # Previous values for delay effect
    prev_control_signal = 0
    prev_room_temp = 25.0
    
    # Simulate from time 1 to simulate_time (inclusive)
    for t in range(1, simulate_time + 1):
        # Find outdoor temperature for this time (use the latest reading <= t)
        outdoor_temp = 25.0  # Default if no reading found
        for time_point, temp in outdoor_temps:
            if time_point <= t:
                outdoor_temp = temp
            else:
                break
        
        # Cap outdoor temperature to previous room temperature
        effective_outdoor_temp = min(outdoor_temp, prev_room_temp)
        
        # Calculate heat loss (10% of the difference)
        heat_loss_temp_c = prev_room_temp - 0.1 * (prev_room_temp - effective_outdoor_temp)
        
        # Apply heater gain (delayed by one step)
        if prev_control_signal == 1:
            heater_output = 0.5
        else:
            heater_output = 0.0
            
        # Calculate new room temperature
        room_temp = heat_loss_temp_c + heater_output
        
        # Determine control signal for next step
        if room_temp < 24.9:
            control_signal = 1
        else:
            control_signal = 0
            
        # Output JSONL record
        output = {
            "time_sec": t,
            "room_temp_c": round(room_temp, 6),
            "heat_loss_temp_c": round(heat_loss_temp_c, 6),
            "control_signal": control_signal,
            "heater_output_c": round(heater_output, 6)
        }
        print(json.dumps(output))
        
        # Update previous values for next iteration
        prev_room_temp = room_temp
        prev_control_signal = control_signal

if __name__ == "__main__":
    main()