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
        time_str, temp_str = line.split()
        timestamp = parse_time(time_str)
        temperature = float(temp_str)
        schedule.append((timestamp, temperature))
    return schedule


def find_outdoor_temp(schedule, time_sec):
    """Find outdoor temperature for given time, using the latest reading <= time"""
    # Sort schedule by timestamp
    schedule.sort(key=lambda x: x[0])
    
    # Find the latest reading with timestamp <= time_sec
    temp = 25.0  # Default temperature
    for timestamp, temperature in schedule:
        if timestamp <= time_sec:
            temp = temperature
        else:
            break
    
    return temp


def simulate_house_heating(simulate_time):
    """Main simulation function"""
    # Parse outdoor temperature schedule from stdin
    schedule = parse_stdin()
    
    # Initial state
    room_temp = 25.0
    control_signal = 0
    heater_output = 0.0
    previous_control_signal = 0
    
    # Convert simulate_time to integer (as per requirements)
    simulate_time = int(simulate_time)
    
    # Simulation loop
    for time_sec in range(1, simulate_time + 1):
        # Find outdoor temperature for this time
        outdoor_temp = find_outdoor_temp(schedule, time_sec)
        
        # Cap outdoor temperature to room temperature (prevent heat gain)
        effective_outdoor_temp = min(outdoor_temp, room_temp)
        
        # Calculate heat loss (10% of the gap)
        heat_loss_temp = room_temp - 0.1 * (room_temp - effective_outdoor_temp)
        
        # Apply heater output from previous step
        if previous_control_signal == 1:
            heater_output = 0.5
        else:
            heater_output = 0.0
            
        # Calculate new room temperature
        room_temp = heat_loss_temp + heater_output
        
        # Determine control signal for next step
        if room_temp < 24.9:
            control_signal = 1
        else:
            control_signal = 0
            
        # Output JSONL record
        output = {
            "time_sec": time_sec,
            "room_temp_c": round(room_temp, 2),
            "heat_loss_temp_c": round(heat_loss_temp, 2),
            "control_signal": control_signal,
            "heater_output_c": heater_output
        }
        
        print(json.dumps(output))
        
        # Update previous control signal for next iteration
        previous_control_signal = control_signal


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulate_time', type=float, required=True,
                       help='Total simulation duration in seconds')
    
    args = parser.parse_args()
    
    simulate_house_heating(args.simulate_time)


if __name__ == "__main__":
    main()