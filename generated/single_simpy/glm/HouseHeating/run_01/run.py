#!/usr/bin/env python3

import argparse
import sys
import json
import bisect
from typing import Dict, List


def parse_time_str(time_str: str) -> int:
    """Parse HH:MM:SS string to total seconds."""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def read_outdoor_schedule() -> tuple[Dict[int, float], List[int]]:
    """Read outdoor temperature schedule from stdin.
    
    Returns a tuple of (schedule_dict, sorted_timestamps_list).
    """
    schedule = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        time_str = parts[0]
        temp = float(parts[1])
        timestamp = parse_time_str(time_str)
        schedule[timestamp] = temp
    sorted_timestamps = sorted(schedule.keys())
    return schedule, sorted_timestamps


def get_outdoor_temp(schedule: Dict[int, float], sorted_timestamps: List[int], t: int) -> float:
    """Get outdoor temperature for time t.
    
    Returns the temperature with greatest timestamp <= t,
    or 25.0 if no such reading exists.
    """
    if not sorted_timestamps:
        return 25.0
    
    # Find the greatest timestamp <= t using binary search
    idx = bisect.bisect_right(sorted_timestamps, t) - 1
    if idx < 0:
        return 25.0
    
    return schedule[sorted_timestamps[idx]]


def main():
    parser = argparse.ArgumentParser(description='House Heating Temperature Control Simulation')
    parser.add_argument('--simulate_time', type=float, required=True,
                        help='Total simulation duration in seconds')
    args = parser.parse_args()
    
    # Read outdoor temperature schedule from stdin
    schedule, sorted_timestamps = read_outdoor_schedule()
    
    # Simulation parameters
    total_time = int(args.simulate_time)
    target_temp = 24.9
    heater_gain = 0.5
    loss_rate = 0.1  # 10%
    
    # Initial state at time 0
    room_temp = 25.0
    control_signal = 0  # control_signal[0]
    
    # Output for each time step from 1 to total_time
    for t in range(1, total_time + 1):
        # Get outdoor temperature for time t-1
        outdoor_temp = get_outdoor_temp(schedule, sorted_timestamps, t - 1)
        
        # Cap outdoor temp to previous room temp (no heat gain from outdoors)
        effective_outdoor_temp = min(outdoor_temp, room_temp)
        
        # Apply heat loss: room loses 10% of gap between room temp and effective outdoor temp
        temp_gap = room_temp - effective_outdoor_temp
        heat_loss = temp_gap * loss_rate
        heat_loss_temp = room_temp - heat_loss
        
        # Heater gain is delayed by one step
        # Heater adds 0.5°C if previous control_signal was 1
        heater_output = heater_gain if control_signal == 1 else 0.0
        
        # New room temperature
        room_temp = heat_loss_temp + heater_output
        
        # Set next control signal based on new room temp
        control_signal = 1 if room_temp < target_temp else 0
        
        # Output the state for time t
        output = {
            "time_sec": t,
            "room_temp_c": room_temp,
            "heat_loss_temp_c": heat_loss_temp,
            "control_signal": control_signal,
            "heater_output_c": heater_output
        }
        
        print(json.dumps(output))


if __name__ == '__main__':
    main()