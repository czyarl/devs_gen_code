#!/usr/bin/env python3
"""
House Heating Temperature Control Simulation

This script simulates a single heated room controlled by a bang-bang heater.
The system models heat loss to the outdoor environment and heater gain.
"""

import argparse
import sys
import json
from typing import Dict, List, Optional


def parse_timestamp(timestamp_str: str) -> int:
    """
    Parse a timestamp in HH:MM:SS format to seconds.
    
    Args:
        timestamp_str: Timestamp string in HH:MM:SS format
        
    Returns:
        Total seconds
    """
    parts = timestamp_str.strip().split(':')
    if len(parts) != 3:
        raise ValueError(f"Invalid timestamp format: {timestamp_str}")
    
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    
    return hours * 3600 + minutes * 60 + seconds


def read_outdoor_temperatures() -> List[tuple]:
    """
    Read outdoor temperature schedule from stdin.
    
    Returns:
        List of (timestamp_seconds, temperature) tuples, sorted by timestamp
    """
    readings = []
    
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split()
        if len(parts) != 2:
            print(f"Warning: Skipping invalid line: {line}", file=sys.stderr)
            continue
        
        timestamp_str = parts[0]
        try:
            temperature = float(parts[1])
        except ValueError:
            print(f"Warning: Skipping line with invalid temperature: {line}", file=sys.stderr)
            continue
        
        try:
            timestamp = parse_timestamp(timestamp_str)
        except ValueError as e:
            print(f"Warning: Skipping line with invalid timestamp: {line} - {e}", file=sys.stderr)
            continue
        
        readings.append((timestamp, temperature))
    
    # Sort by timestamp
    readings.sort(key=lambda x: x[0])
    return readings


def get_outdoor_temperature(time_sec: int, readings: List[tuple]) -> float:
    """
    Get the outdoor temperature at a given simulation time.
    
    For any simulation time t, use the reading with the greatest timestamp
    less than or equal to t. If there is no such reading, use 25.0.
    
    Args:
        time_sec: Current simulation time in seconds
        readings: List of (timestamp, temperature) tuples
        
    Returns:
        Outdoor temperature at the given time
    """
    # Find the reading with the greatest timestamp <= time_sec
    for i in range(len(readings) - 1, -1, -1):
        if readings[i][0] <= time_sec:
            return readings[i][1]
    
    # No reading found, use default
    return 25.0


def simulate(simulate_time: float, outdoor_readings: List[tuple]):
    """
    Run the house heating simulation.
    
    Args:
        simulate_time: Total simulation duration in seconds
        outdoor_readings: List of (timestamp, temperature) tuples for outdoor temps
    """
    # Convert to integer number of steps
    num_steps = int(simulate_time)
    
    # Initial state at time 0
    room_temp = 25.0  # degrees Celsius
    control_signal = 0  # heater is off initially
    heater_output = 0.0  # degrees Celsius
    
    # Simulate each time step from 1 to num_steps
    for t in range(1, num_steps + 1):
        # Get outdoor temperature at previous time step (t-1)
        outdoor_temp = get_outdoor_temperature(t - 1, outdoor_readings)
        
        # Cap outdoor temperature to previous room temperature
        # This prevents outdoor heat gain
        effective_outdoor_temp = min(outdoor_temp, room_temp)
        
        # Apply heat loss: room loses 10% of the gap between its temperature
        # and the effective outdoor temperature
        temp_gap = room_temp - effective_outdoor_temp
        heat_loss_temp = room_temp - (0.1 * temp_gap)
        
        # Heater gain is delayed by one step: heater adds 0.5 degrees
        # only if the previous control signal was 1
        heater_output = 0.5 if control_signal == 1 else 0.0
        
        # New room temperature is heat-loss value plus heater gain
        new_room_temp = heat_loss_temp + heater_output
        
        # Record the observable state for this time step
        state = {
            "time_sec": t,
            "room_temp_c": round(new_room_temp, 6),
            "heat_loss_temp_c": round(heat_loss_temp, 6),
            "control_signal": control_signal,
            "heater_output_c": round(heater_output, 6)
        }
        
        # Output JSONL record
        print(json.dumps(state))
        
        # Update room temperature for next iteration
        room_temp = new_room_temp
        
        # Set next control signal: 1 if room is below 24.9, otherwise 0
        control_signal = 1 if room_temp < 24.9 else 0


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
    outdoor_readings = read_outdoor_temperatures()
    
    if outdoor_readings:
        print(f"Read {len(outdoor_readings)} outdoor temperature readings", file=sys.stderr)
    else:
        print("No outdoor temperature readings provided, using default 25.0", file=sys.stderr)
    
    # Run the simulation
    simulate(args.simulate_time, outdoor_readings)


if __name__ == "__main__":
    main()
