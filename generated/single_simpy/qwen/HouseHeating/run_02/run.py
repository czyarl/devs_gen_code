import argparse
import json
import sys
from datetime import datetime, timedelta

def parse_time(time_str):
    """Parse HH:MM:SS format to seconds since midnight"""
    h, m, s = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s

def parse_stdin():
    """Parse stdin to create outdoor temperature schedule"""
    schedule = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        time_str, temp_str = line.split()
        timestamp = parse_time(time_str)
        temperature = float(temp_str)
        schedule.append((timestamp, temperature))
    return sorted(schedule)

def get_outdoor_temp(schedule, time_sec):
    """Get outdoor temperature for given time"""
    # Find latest reading <= time_sec
    temp = 25.0  # default
    for timestamp, temperature in schedule:
        if timestamp <= time_sec:
            temp = temperature
        else:
            break
    return temp

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulate_time', type=float, required=True)
    args = parser.parse_args()
    
    simulate_time = int(args.simulate_time)
    
    # Parse outdoor temperature schedule
    schedule = parse_stdin()
    
    # Initial state
    room_temp = 25.0
    control_signal = 0
    heater_output = 0.0
    
    # Output initial state at time 0 (not required by spec but good for reference)
    # We start at time 1 according to spec
    
    # Simulation loop
    for time_sec in range(1, simulate_time + 1):
        # Get effective outdoor temperature (capped at room temperature)
        outdoor_temp = get_outdoor_temp(schedule, time_sec - 1)
        effective_outdoor_temp = min(outdoor_temp, room_temp)
        
        # Calculate heat loss (10% of the difference)
        heat_loss_temp = room_temp - 0.1 * (room_temp - effective_outdoor_temp)
        
        # Apply heater output from previous step
        new_room_temp = heat_loss_temp + heater_output
        
        # Determine control signal for next step
        new_control_signal = 1 if new_room_temp < 24.9 else 0
        
        # Determine heater output for current step
        new_heater_output = 0.5 if control_signal == 1 else 0.0
        
        # Output JSONL record
        record = {
            "time_sec": time_sec,
            "room_temp_c": new_room_temp,
            "heat_loss_temp_c": heat_loss_temp,
            "control_signal": new_control_signal,
            "heater_output_c": new_heater_output
        }
        
        print(json.dumps(record))
        
        # Update state for next iteration
        room_temp = new_room_temp
        control_signal = new_control_signal
        heater_output = new_heater_output

if __name__ == "__main__":
    main()