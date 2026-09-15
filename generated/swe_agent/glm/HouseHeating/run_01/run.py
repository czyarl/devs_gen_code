#!/usr/bin/env python3
"""
House Heating Temperature Control Simulation

This script simulates a single heated room controlled by a bang-bang heater.
The system models heat loss to the outdoor environment and heater gain.
"""

import argparse
import json
import sys
from typing import Dict, List, Optional


def parse_timestamp(timestamp_str: str) -> int:
    """
    Parse a timestamp in HH:MM:SS format to seconds.
    
    Args:
        timestamp_str: Timestamp string in HH:MM:SS format
        
    Returns:
        Total seconds
    """
    parts = timestamp_str.split(':')
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp format: {timestamp_str}")
    
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    
    return hours * 3600 + minutes * 60 + seconds


def read_outdoor_temperatures() -> Dict[int, float]:
    """
    Read outdoor temperature schedule from stdin.
    
    Returns:
        Dictionary mapping timestamps (in seconds) to outdoor temperatures
    """
    outdoor_temps = {}
    
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split()
        if len(parts) != 2:
            print(f"Warning: Skipping invalid line: {line}", file=sys.stderr)
            continue
        
        timestamp_str, temp_str = parts
        timestamp = parse_timestamp(timestamp_str)
        temp = float(temp_str)
        
        outdoor_temps[timestamp] = temp
    
    return outdoor_temps


def get_outdoor_temperature(outdoor_temps: Dict[int, float], time_sec: int) -> float:
    """
    Get the outdoor temperature at a given simulation time.
    
    For any simulation time t, use the reading with the greatest timestamp
    less than or equal to t. If there is no such reading, use 25.0.
    
    Args:
        outdoor_temps: Dictionary of timestamped outdoor temperatures
        time_sec: Current simulation time in seconds
        
    Returns:
        Outdoor temperature at the given time
    """
    # Find the greatest timestamp <= time_sec
    valid_timestamps = [ts for ts in outdoor_temps.keys() if ts <= time_sec]
    
    if not valid_timestamps:
        return 25.0
    
    latest_timestamp = max(valid_timestamps)
    return outdoor_temps[latest_timestamp]


def simulate(
    simulate_time: float,
    outdoor_temps: Dict[int, float]
) -> List[Dict]:
    """
    Run the house heating simulation.
    
    Args:
        simulate_time: Total simulation duration in seconds
        outdoor_temps: Dictionary of timestamped outdoor temperatures
        
    Returns:
        List of observation records
    """
    observations = []
    
    # Initial state at time 0
    room_temp = 25.0
    control_signal = 0
    heater_output = 0.0
    
    # Number of observations to generate
    num_steps = int(simulate_time)
    
    for t in range(1, num_steps + 1):
        # Get outdoor temperature for the previous second
        outdoor_temp = get_outdoor_temperature(outdoor_temps, t - 1)
        
        # Cap outdoor temperature to previous room temperature
        # This prevents outdoor heat gain
        effective_outdoor_temp = min(outdoor_temp, room_temp)
        
        # Calculate heat loss: room loses 10% of the gap between its
        # previous temperature and the effective outdoor temperature
        temp_gap = room_temp - effective_outdoor_temp
        heat_loss_temp_c = room_temp - 0.1 * temp_gap
        
        # Heater gain is delayed by one step
        # Heater adds 0.5 degrees if previous control signal was 1
        heater_output_c = 0.5 if control_signal == 1 else 0.0
        
        # New room temperature is heat-loss value plus heater gain
        room_temp = heat_loss_temp_c + heater_output_c
        
        # Record observation
        observation = {
            "time_sec": t,
            "room_temp_c": room_temp,
            "heat_loss_temp_c": heat_loss_temp_c,
            "control_signal": control_signal,
            "heater_output_c": heater_output_c
        }
        observations.append(observation)
        
        # Set next control signal based on new room temperature
        # Heater turns on when room is below 24.9 degrees
        control_signal = 1 if room_temp < 24.9 else 0
    
    return observations


def main():
    """Main entry point for the simulation."""
    parser = argparse.ArgumentParser(
        description="House Heating Temperature Control Simulation"
    )
    parser.add_argument(
        "--simulate_time",
        type=float,
        required=True,
        help="Total simulation duration in seconds"
    )
    
    args = parser.parse_args()
    
    # Read outdoor temperature schedule from stdin
    outdoor_temps = read_outdoor_temperatures()
    
    # Run simulation
    observations = simulate(args.simulate_time, outdoor_temps)
    
    # Output observations as JSONL
    for obs in observations:
        print(json.dumps(obs))


if __name__ == "__main__":
    main()
