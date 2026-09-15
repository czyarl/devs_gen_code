#!/usr/bin/env python3
"""
House Heating Temperature Control Simulation

This script simulates a single heated room controlled by a bang-bang heater.
Outdoor temperature varies over time and affects heat loss. The controller
tries to keep the room near the target temperature of 24.9 degrees Celsius.
"""

import argparse
import json
import sys
from typing import Dict, List, Tuple


def parse_time_to_seconds(time_str: str) -> int:
    """
    Parse a time string in HH:MM:SS format to seconds.
    
    Args:
        time_str: Time string in format "HH:MM:SS"
        
    Returns:
        Time in seconds
    """
    parts = time_str.strip().split(':')
    if len(parts) != 3:
        raise ValueError(f"Invalid time format: {time_str}")
    
    hours, minutes, seconds = map(int, parts)
    return hours * 3600 + minutes * 60 + seconds


def read_outdoor_temperatures() -> List[Tuple[int, float]]:
    """
    Read outdoor temperature schedule from stdin.
    
    Each non-empty line contains a timestamp in HH:MM:SS format followed
    by one numeric outdoor temperature.
    
    Returns:
        List of (timestamp_seconds, temperature) tuples sorted by timestamp
    """
    temperatures = []
    
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split()
        if len(parts) < 2:
            continue
        
        time_str = parts[0]
        temp = float(parts[1])
        
        timestamp = parse_time_to_seconds(time_str)
        temperatures.append((timestamp, temp))
    
    # Sort by timestamp
    temperatures.sort(key=lambda x: x[0])
    return temperatures


def get_outdoor_temperature(
    current_time: int,
    outdoor_schedule: List[Tuple[int, float]]
) -> float:
    """
    Get the outdoor temperature at a given simulation time.
    
    For any simulation time t, use the reading with the greatest timestamp
    less than or equal to t. If there is no such reading, use 25.0.
    
    Args:
        current_time: Current simulation time in seconds
        outdoor_schedule: List of (timestamp, temperature) tuples
        
    Returns:
        Outdoor temperature at current_time
    """
    # Find the greatest timestamp <= current_time
    for timestamp, temp in reversed(outdoor_schedule):
        if timestamp <= current_time:
            return temp
    
    # Default temperature if no reading found
    return 25.0


def simulate_heating(
    simulate_time: float,
    outdoor_schedule: List[Tuple[int, float]]
) -> None:
    """
    Run the house heating simulation.
    
    Args:
        simulate_time: Total simulation duration in seconds
        outdoor_schedule: List of (timestamp, temperature) tuples
    """
    # Initial state at time 0
    room_temp_c = 25.0
    control_signal = 0  # control_signal[0] = 0
    heater_output_c = 0.0
    
    # Target temperature for controller
    target_temp_c = 24.9
    
    # Number of observations to produce
    num_observations = int(simulate_time)
    
    # Simulate each second from 1 to num_observations
    for time_sec in range(1, num_observations + 1):
        # Get outdoor temperature from previous second
        outdoor_temp = get_outdoor_temperature(time_sec - 1, outdoor_schedule)
        
        # Cap outdoor temperature to previous room temperature
        # This prevents outdoor heat gain
        effective_outdoor_temp = min(outdoor_temp, room_temp_c)
        
        # Calculate heat loss: room loses 10% of the gap between
        # its previous temperature and effective outdoor temperature
        temp_gap = room_temp_c - effective_outdoor_temp
        heat_loss_temp_c = room_temp_c - (0.1 * temp_gap)
        
        # Heater gain is delayed by one step: heater adds 0.5 degrees
        # during current step only if previous control signal was 1
        heater_output_c = 0.5 if control_signal == 1 else 0.0
        
        # New room temperature is heat-loss value plus heater gain
        room_temp_c = heat_loss_temp_c + heater_output_c
        
        # Output the observation for this time step
        observation = {
            "time_sec": time_sec,
            "room_temp_c": room_temp_c,
            "heat_loss_temp_c": heat_loss_temp_c,
            "control_signal": control_signal,
            "heater_output_c": heater_output_c
        }
        
        print(json.dumps(observation))
        
        # After new room temperature is known, set next control signal
        # Controller sets control signal to 1 when room is below 24.9,
        # otherwise 0
        control_signal = 1 if room_temp_c < target_temp_c else 0


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
    outdoor_schedule = read_outdoor_temperatures()
    
    # Run the simulation
    simulate_heating(args.simulate_time, outdoor_schedule)


if __name__ == "__main__":
    main()
