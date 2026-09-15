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
        timestamp, temp = parts
        try:
            time_sec = parse_time(timestamp)
            temp = float(temp)
            schedule.append((time_sec, temp))
        except ValueError:
            continue
    # Sort schedule by time
    schedule.sort()
    return schedule

def get_outdoor_temp(schedule, time_sec):
    """Get outdoor temperature for given time, using the latest reading <= time_sec"""
    # Find the latest reading with timestamp <= time_sec
    latest_reading = None
    for t, temp in schedule:
        if t <= time_sec:
            if latest_reading is None or t > latest_reading[0]:
                latest_reading = (t, temp)
    
    # If no reading found, use 25.0
    if latest_reading is None:
        return 25.0
    
    return latest_reading[1]

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
        # Get outdoor temperature for the previous second (time_sec - 1)
        outdoor_temp = get_outdoor_temp(schedule, time_sec - 1)
        
        # Cap outdoor temperature to room temperature to prevent direct heat gain
        effective_outdoor_temp = min(outdoor_temp, room_temp)
        
        # Calculate heat loss (10% of the gap)
        heat_loss = 0.1 * (room_temp - effective_outdoor_temp)
        heat_loss_temp_c = room_temp - heat_loss
        
        # Apply heater gain (delayed by one step)
        heater_output = 0.5 if control_signal == 1 else 0.0
        
        # Update room temperature
        room_temp = heat_loss_temp_c + heater_output
        
        # Determine next control signal
        next_control_signal = 1 if room_temp < 24.9 else 0
        
        # Output JSONL record
        record = {
            "time_sec": time_sec,
            "room_temp_c": round(room_temp, 5),
            "heat_loss_temp_c": round(heat_loss_temp_c, 5),
            "control_signal": next_control_signal,
            "heater_output_c": round(heater_output, 5)
        }
        
        print(json.dumps(record))
        
        # Update control signal for next iteration
        control_signal = next_control_signal

if __name__ == "__main__":
    main()