import argparse
import json
import sys
from datetime import datetime, timedelta

def parse_time(time_str):
    """Parse HH:MM:SS format to seconds since midnight"""
    h, m, s = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulate_time', type=float, required=True)
    args = parser.parse_args()
    
    # Read outdoor temperature schedule
    outdoor_temps = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        timestamp = parse_time(parts[0])
        temp = float(parts[1])
        outdoor_temps.append((timestamp, temp))
    
    # Sort by timestamp
    outdoor_temps.sort()
    
    # Simulation parameters
    simulate_time = int(args.simulate_time)
    initial_room_temp = 25.0
    
    # Initialize state
    room_temp = initial_room_temp
    prev_control_signal = 0
    prev_time = 0
    
    # Process each second of simulation
    for t in range(1, simulate_time + 1):
        # Find the appropriate outdoor temperature
        outdoor_temp = 25.0
        for timestamp, temp in outdoor_temps:
            if timestamp <= t:
                outdoor_temp = temp
            else:
                break
        
        # Cap outdoor temperature to room temperature if needed
        effective_outdoor_temp = min(outdoor_temp, room_temp)
        
        # Compute heat loss (10% of the difference)
        heat_loss_temp = room_temp - 0.1 * (room_temp - effective_outdoor_temp)
        
        # Apply heater gain (delayed by one step)
        heater_output = 0.5 if prev_control_signal == 1 else 0.0
        
        # Compute new room temperature
        room_temp = heat_loss_temp + heater_output
        
        # Determine control signal for next step
        control_signal = 1 if room_temp < 24.9 else 0
        
        # Output JSONL record
        record = {
            "time_sec": t,
            "room_temp_c": round(room_temp, 6),
            "heat_loss_temp_c": round(heat_loss_temp, 6),
            "control_signal": control_signal,
            "heater_output_c": heater_output
        }
        print(json.dumps(record))
        
        # Update state for next iteration
        prev_control_signal = control_signal

if __name__ == "__main__":
    main()