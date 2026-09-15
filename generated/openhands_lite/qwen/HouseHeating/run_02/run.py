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
        try:
            timestamp = parse_time(time_str)
            temperature = float(temp_str)
            schedule[timestamp] = temperature
        except ValueError:
            continue
    return schedule


def get_outdoor_temp(schedule, time_sec):
    """Get outdoor temperature for given time, using the latest reading <= time_sec"""
    # Find the latest timestamp that is <= time_sec
    valid_timestamps = [t for t in schedule.keys() if t <= time_sec]
    if not valid_timestamps:
        # If no previous reading, use default 25.0
        return 25.0
    latest_timestamp = max(valid_timestamps)
    return schedule[latest_timestamp]


def simulate_house_heating(simulate_time):
    """Run the house heating simulation"""
    # Parse outdoor temperature schedule
    outdoor_schedule = parse_outdoor_schedule()
    
    # Initialize simulation state
    room_temp = 25.0  # Initial room temperature
    control_signal = 0  # Initial control signal (heater off)
    heater_output = 0.0  # Initial heater output
    
    # Store previous values for next step calculations
    prev_room_temp = room_temp
    prev_control_signal = control_signal
    
    # Output the initial state (time 0)
    # Note: The problem states observations start from time 1, but we need to initialize
    # the simulation state properly
    
    # Simulate from time 1 to simulate_time (inclusive)
    for time_sec in range(1, int(simulate_time) + 1):
        # Get the outdoor temperature for the previous second
        outdoor_temp = get_outdoor_temp(outdoor_schedule, time_sec - 1)
        
        # Cap outdoor temperature to not exceed room temperature
        effective_outdoor_temp = min(outdoor_temp, prev_room_temp)
        
        # Calculate heat loss (10% of the gap)
        heat_loss = 0.1 * (prev_room_temp - effective_outdoor_temp)
        heat_loss_temp_c = prev_room_temp - heat_loss
        
        # Apply heater gain (delayed by one step)
        # Heater adds 0.5°C if previous control signal was 1, otherwise 0.0°C
        heater_output = 0.5 if prev_control_signal == 1 else 0.0
        
        # Calculate new room temperature
        room_temp = heat_loss_temp_c + heater_output
        
        # Determine next control signal
        # Heater on if room temp is below 24.9°C, off otherwise
        next_control_signal = 1 if room_temp < 24.9 else 0
        
        # Output the observation for this time step
        observation = {
            "time_sec": time_sec,
            "room_temp_c": room_temp,
            "heat_loss_temp_c": heat_loss_temp_c,
            "control_signal": next_control_signal,
            "heater_output_c": heater_output
        }
        
        print(json.dumps(observation))
        
        # Update state for next iteration
        prev_room_temp = room_temp
        prev_control_signal = next_control_signal


def main():
    parser = argparse.ArgumentParser(description='House Heating Temperature Control Simulation')
    parser.add_argument('--simulate_time', type=float, required=True,
                       help='Total simulation duration in seconds')
    
    args = parser.parse_args()
    
    simulate_house_heating(args.simulate_time)


if __name__ == '__main__':
    main()