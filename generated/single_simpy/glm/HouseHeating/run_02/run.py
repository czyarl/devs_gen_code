#!/usr/bin/env python3
import argparse
import bisect
import json
import sys
from typing import Dict


def parse_time(time_str: str) -> int:
    """Parse HH:MM:SS format to seconds."""
    parts = time_str.split(':')
    if len(parts) != 3:
        raise ValueError(f"Invalid time format: {time_str}")
    hours, minutes, seconds = map(int, parts)
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
        if len(parts) != 2:
            continue
        time_str, temp_str = parts
        try:
            timestamp = parse_time(time_str)
            temperature = float(temp_str)
            schedule[timestamp] = temperature
        except (ValueError, IndexError):
            continue
    return schedule


def simulate(simulate_time: float, outdoor_schedule: Dict[int, float]):
    """Run the simulation and output JSONL records."""
    max_time = int(simulate_time)
    
    # Sort the timestamps for efficient lookup
    sorted_timestamps = sorted(outdoor_schedule.keys())
    
    def get_outdoor_temperature(time_sec: int) -> float:
        """Get outdoor temperature at a given time.
        
        Uses the reading with the greatest timestamp <= time_sec.
        If no such reading, returns 25.0.
        """
        if not sorted_timestamps:
            return 25.0
        
        # Binary search for the greatest timestamp <= time_sec
        idx = bisect.bisect_right(sorted_timestamps, time_sec) - 1
        if idx < 0:
            return 25.0
        
        return outdoor_schedule[sorted_timestamps[idx]]
    
    # Initial state at time 0
    room_temp = 25.0
    control_signal = 0  # This determines heating from 0 to 1
    
    # Output observations for seconds 1..max_time
    for t in range(1, max_time + 1):
        # Get outdoor temperature from previous second
        outdoor_temp = get_outdoor_temperature(t - 1)
        
        # Cap outdoor temperature to previous room temperature
        effective_outdoor = min(outdoor_temp, room_temp)
        
        # Apply heat loss: lose 10% of the gap
        gap = room_temp - effective_outdoor
        heat_loss_temp = room_temp - 0.1 * gap
        
        # Heater gain is delayed by one step
        heater_gain = 0.5 if control_signal == 1 else 0.0
        
        # New room temperature
        new_room_temp = heat_loss_temp + heater_gain
        
        # This is the heater output for this step
        heater_output = heater_gain
        
        # Set next control signal
        next_control_signal = 1 if new_room_temp < 24.9 else 0
        
        # Output the state at time t
        output = {
            "time_sec": t,
            "room_temp_c": new_room_temp,
            "heat_loss_temp_c": heat_loss_temp,
            "control_signal": next_control_signal,
            "heater_output_c": heater_output
        }
        print(json.dumps(output))
        
        # Update state for next iteration
        room_temp = new_room_temp
        control_signal = next_control_signal


def main():
    parser = argparse.ArgumentParser(description="House Heating Temperature Control Simulation")
    parser.add_argument("--simulate_time", type=float, required=True,
                        help="Total simulation duration in seconds")
    args = parser.parse_args()
    
    # Read outdoor temperature schedule from stdin
    outdoor_schedule = read_outdoor_schedule()
    
    # Run simulation
    simulate(args.simulate_time, outdoor_schedule)


if __name__ == "__main__":
    main()