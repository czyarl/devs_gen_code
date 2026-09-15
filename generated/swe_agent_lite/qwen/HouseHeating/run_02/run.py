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


def get_outdoor_temp(schedule, time_sec):
    """Get outdoor temperature for given time, using the latest reading <= time"""
    # Find the latest reading with timestamp <= time_sec
    temp_at_time = 25.0  # Default temperature
    for timestamp, temperature in schedule:
        if timestamp <= time_sec:
            temp_at_time = temperature
        else:
            break
    return temp_at_time


def simulate_house_heating(simulate_time, schedule):
    """Main simulation function"""
    # Initial state
    room_temp = 25.0
    control_signal = 0
    heater_output = 0.0
    
    # Store previous values for next step calculations
    prev_control_signal = 0
    prev_room_temp = 25.0
    
    # Output observations for integer seconds 1 through int(simulate_time)
    for time_sec in range(1, int(simulate_time) + 1):
        # Get outdoor temperature for the previous second
        outdoor_temp = get_outdoor_temp(schedule, time_sec - 1)
        
        # Cap outdoor temperature to room temperature to prevent heat gain
        effective_outdoor_temp = min(outdoor_temp, prev_room_temp)
        
        # Calculate heat loss (10% of the gap)
        heat_loss = 0.1 * (prev_room_temp - effective_outdoor_temp)
        heat_loss_temp_c = prev_room_temp - heat_loss
        
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
        observation = {
            "time_sec": time_sec,
            "room_temp_c": round(room_temp, 6),
            "heat_loss_temp_c": round(heat_loss_temp_c, 6),
            "control_signal": control_signal,
            "heater_output_c": round(heater_output, 6)
        }
        
        print(json.dumps(observation))
        
        # Update previous values for next iteration
        prev_room_temp = room_temp
        prev_control_signal = control_signal


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='House Heating Temperature Control Simulation')
    parser.add_argument('--simulate_time', type=float, required=True, 
                       help='Total simulation duration in seconds')
    
    args = parser.parse_args()
    
    # Parse outdoor temperature schedule from stdin
    schedule = parse_stdin()
    
    # Run simulation
    simulate_house_heating(args.simulate_time, schedule)


if __name__ == '__main__':
    main()