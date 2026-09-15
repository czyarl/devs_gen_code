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
    schedule = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        time_str, temp_str = parts
        timestamp = parse_time(time_str)
        temperature = float(temp_str)
        schedule[timestamp] = temperature
    return schedule


def get_outdoor_temperature(schedule, time_sec):
    """Get outdoor temperature at given time, using the latest reading <= time_sec"""
    # Find the latest timestamp that is <= time_sec
    valid_timestamps = [ts for ts in schedule.keys() if ts <= time_sec]
    if not valid_timestamps:
        # No reading found, return default 25.0
        return 25.0
    latest_timestamp = max(valid_timestamps)
    return schedule[latest_timestamp]


def simulate_house_heating(simulate_time, outdoor_schedule):
    """Run the discrete event simulation"""
    # Initial state
    room_temp = 25.0
    control_signal = 0
    heater_output = 0.0
    
    # Store the previous control signal for heater delay
    prev_control_signal = 0
    
    # Convert simulate_time to integer (as specified)
    simulate_time = int(simulate_time)
    
    # Process each second from 1 to simulate_time
    for time_sec in range(1, simulate_time + 1):
        # Get outdoor temperature for this time step
        outdoor_temp = get_outdoor_temperature(outdoor_schedule, time_sec)
        
        # Cap outdoor temperature to not exceed room temperature
        effective_outdoor_temp = min(outdoor_temp, room_temp)
        
        # Calculate heat loss (10% of the difference)
        heat_loss_temp = room_temp - 0.1 * (room_temp - effective_outdoor_temp)
        
        # Apply heater gain from previous control signal (delayed by 1 step)
        if prev_control_signal == 1:
            heater_output = 0.5
        else:
            heater_output = 0.0
            
        # Calculate new room temperature
        room_temp = heat_loss_temp + heater_output
        
        # Determine next control signal based on room temperature
        if room_temp < 24.9:
            control_signal = 1
        else:
            control_signal = 0
            
        # Prepare output record
        output_record = {
            "time_sec": time_sec,
            "room_temp_c": round(room_temp, 6),
            "heat_loss_temp_c": round(heat_loss_temp, 6),
            "control_signal": control_signal,
            "heater_output_c": round(heater_output, 6)
        }
        
        # Print JSONL record to stdout
        print(json.dumps(output_record))
        
        # Update previous control signal for next iteration
        prev_control_signal = control_signal


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='House Heating Temperature Control Simulation')
    parser.add_argument('--simulate_time', type=float, required=True, 
                       help='Total simulation duration in seconds')
    
    args = parser.parse_args()
    
    # Parse outdoor temperature schedule from stdin
    outdoor_schedule = parse_outdoor_schedule()
    
    # Run simulation
    simulate_house_heating(args.simulate_time, outdoor_schedule)


if __name__ == '__main__':
    main()