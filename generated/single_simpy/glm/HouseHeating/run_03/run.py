#!/usr/bin/env python3
"""
House Heating Temperature Control Simulation

This script simulates a single heated room controlled by a bang-bang heater.
The outdoor temperature varies over time and affects heat loss.
The controller tries to keep the room near the target temperature of 24.9°C.
"""
import argparse
import json
import sys
from typing import Dict


def parse_hhmmss(time_str: str) -> int:
    """Convert HH:MM:SS string to seconds."""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def read_outdoor_schedule() -> Dict[int, float]:
    """Read outdoor temperature schedule from stdin.
    
    Returns a dictionary mapping timestamp (in seconds) to temperature.
    """
    schedule = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        time_str = parts[0]
        temp = float(parts[1])
        timestamp = parse_hhmmss(time_str)
        schedule[timestamp] = temp
    return schedule


def get_outdoor_temp(schedule: Dict[int, float], t: int) -> float:
    """Get outdoor temperature for time t.
    
    Uses the reading with the greatest timestamp <= t.
    If no such reading, returns 25.0.
    """
    if not schedule:
        return 25.0
    
    # Find the greatest timestamp <= t
    valid_timestamps = [ts for ts in schedule.keys() if ts <= t]
    if not valid_timestamps:
        return 25.0
    
    latest_timestamp = max(valid_timestamps)
    return schedule[latest_timestamp]


def simulate(simulate_time: float):
    """Run the heating simulation."""
    total_seconds = int(simulate_time)
    
    # Read outdoor temperature schedule
    outdoor_schedule = read_outdoor_schedule()
    
    # Initial state at time 0
    room_temp = 25.0
    control_signal = 0
    
    # Output observations for seconds 1..total_seconds
    for t in range(1, total_seconds + 1):
        # Get outdoor temperature for previous second (t-1)
        outdoor_temp = get_outdoor_temp(outdoor_schedule, t - 1)
        
        # Cap outdoor temperature to previous room temperature
        effective_outdoor = min(outdoor_temp, room_temp)
        
        # Apply heat loss: room loses 10% of the gap
        gap = room_temp - effective_outdoor
        heat_loss_temp = room_temp - 0.1 * gap
        
        # Heater gain is delayed: uses previous control signal
        heater_gain = 0.5 if control_signal == 1 else 0.0
        
        # New room temperature
        new_room_temp = heat_loss_temp + heater_gain
        
        # Record observation for time t
        observation = {
            "time_sec": t,
            "room_temp_c": new_room_temp,
            "heat_loss_temp_c": heat_loss_temp,
            "control_signal": control_signal,
            "heater_output_c": heater_gain
        }
        print(json.dumps(observation))
        
        # Update state for next iteration
        room_temp = new_room_temp
        
        # Set next control signal based on new room temperature
        control_signal = 1 if room_temp < 24.9 else 0


def main():
    parser = argparse.ArgumentParser(description="House Heating Temperature Control Simulation")
    parser.add_argument("--simulate_time", type=float, required=True,
                        help="Total simulation duration in seconds")
    args = parser.parse_args()
    
    simulate(args.simulate_time)


if __name__ == "__main__":
    main()