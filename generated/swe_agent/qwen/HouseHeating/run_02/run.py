#!/usr/bin/env python3

import argparse
import sys
import json

def parse_time(time_str):
    """Parse HH:MM:SS format to seconds since midnight"""
    h, m, s = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s

def parse_input():
    """Parse stdin input into a list of (timestamp, temperature) tuples"""
    readings = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            timestamp = parse_time(parts[0])
            temperature = float(parts[1])
            readings.append((timestamp, temperature))
    return sorted(readings, key=lambda x: x[0])

def get_outdoor_temp(readings, time_sec):
    """Get outdoor temperature for a given time"""
    # Find the reading with greatest timestamp <= time_sec
    temp = 25.0  # default temperature
    for timestamp, temperature in readings:
        if timestamp <= time_sec:
            temp = temperature
        else:
            break
    return temp

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulate_time', type=float, required=True, 
                       help='Total simulation duration in seconds')
    args = parser.parse_args()
    
    # Parse input
    readings = parse_input()
    
    # Get simulation time
    simulate_time = int(args.simulate_time)
    
    # Initialize state
    room_temp = 25.0
    control_signal = 0  # Initial control signal is 0
    heater_output = 0.0  # Initial heater output is 0.0
    
    # For time 0, we don't output anything, but we need to track the previous state
    # to compute the next step correctly
    
    # Simulation loop
    for time_sec in range(1, simulate_time + 1):
        # Get outdoor temperature for the previous second (time_sec - 1)
        outdoor_temp = get_outdoor_temp(readings, time_sec - 1)
        
        # Cap outdoor temperature to room temperature to prevent heat gain
        effective_outdoor_temp = min(outdoor_temp, room_temp)
        
        # Calculate heat loss (10% of the gap)
        heat_loss_temp = room_temp - 0.1 * (room_temp - effective_outdoor_temp)
        
        # Apply heater gain from previous control signal
        # The heater gain is delayed by one step
        if control_signal == 1:
            heater_output = 0.5
        else:
            heater_output = 0.0
            
        # Calculate new room temperature
        room_temp = heat_loss_temp + heater_output
        
        # Determine next control signal (based on current room temperature)
        # This should be done AFTER we calculate the new room temperature
        if room_temp < 24.9:
            next_control_signal = 1
        else:
            next_control_signal = 0
            
        # Output JSONL record
        output = {
            "time_sec": time_sec,
            "room_temp_c": room_temp,
            "heat_loss_temp_c": heat_loss_temp,
            "control_signal": control_signal,  # This is the control signal for this time step
            "heater_output_c": heater_output  # This is the heater output for this time step
        }
        
        print(json.dumps(output))
        
        # Update control signal for next iteration
        control_signal = next_control_signal

if __name__ == "__main__":
    main()