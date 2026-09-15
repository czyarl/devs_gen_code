#!/usr/bin/env python3
"""
House Heating Temperature Control Simulation

A discrete-event simulation of a single heated room controlled by a bang-bang heater.
"""

import argparse
import json
import sys
from typing import Dict, List, Optional


def parse_time_to_seconds(time_str: str) -> int:
    """Convert HH:MM:SS format to seconds."""
    parts = time_str.split(':')
    if len(parts) != 3:
        raise ValueError(f"Invalid time format: {time_str}")
    hours, minutes, seconds = map(int, parts)
    return hours * 3600 + minutes * 60 + seconds


def parse_outdoor_temperatures() -> Dict[int, float]:
    """
    Parse outdoor temperature schedule from stdin.
    
    Returns a dictionary mapping timestamp (in seconds) to temperature.
    """
    temps = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        time_str, temp_str = parts
        timestamp = parse_time_to_seconds(time_str)
        temp = float(temp_str)
        temps[timestamp] = temp
    return temps


def get_outdoor_temperature(temps: Dict[int, float], time_sec: int) -> float:
    """
    Get the outdoor temperature at a given simulation time.
    
    Uses the reading with the greatest timestamp <= time_sec.
    If no such reading exists, returns 25.0.
    """
    # Find the greatest timestamp <= time_sec
    valid_timestamps = [ts for ts in temps.keys() if ts <= time_sec]
    if not valid_timestamps:
        return 25.0
    return temps[max(valid_timestamps)]


def simulate_heating(simulate_time: float, outdoor_temps: Dict[int, float]) -> List[Dict]:
    """
    Run the heating simulation.
    
    Args:
        simulate_time: Total simulation duration in seconds
        outdoor_temps: Dictionary mapping timestamps to outdoor temperatures
    
    Returns:
        List of observation dictionaries for each integer second from 1 to int(simulate_time)
    """
    num_steps = int(simulate_time)
    observations = []
    
    # Initial state at time 0
    room_temp = 25.0
    control_signal = 0
    heater_output = 0.0
    
    # Simulate each time step
    for t in range(1, num_steps + 1):
        # Get outdoor temperature at previous time step (t-1)
        outdoor_temp = get_outdoor_temperature(outdoor_temps, t - 1)
        
        # Cap outdoor temperature to previous room temperature
        # This prevents outdoor heat gain
        effective_outdoor_temp = min(outdoor_temp, room_temp)
        
        # Calculate heat loss: room loses 10% of the gap between its temperature
        # and the effective outdoor temperature
        temp_gap = room_temp - effective_outdoor_temp
        heat_loss_temp = room_temp - 0.1 * temp_gap
        
        # Heater gain is delayed by one step: heater adds 0.5 degrees during
        # the current step only if the previous control signal was 1
        heater_gain = 0.5 if control_signal == 1 else 0.0
        
        # New room temperature is heat-loss value plus heater gain
        new_room_temp = heat_loss_temp + heater_gain
        
        # Record the observation
        observation = {
            "time_sec": t,
            "room_temp_c": new_room_temp,
            "heat_loss_temp_c": heat_loss_temp,
            "control_signal": control_signal,
            "heater_output_c": heater_gain
        }
        observations.append(observation)
        
        # Update state for next iteration
        room_temp = new_room_temp
        
        # Set next control signal: 1 when room is below 24.9, 0 otherwise
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
    
    # Parse outdoor temperature schedule from stdin
    outdoor_temps = parse_outdoor_temperatures()
    
    # Run simulation
    observations = simulate_heating(args.simulate_time, outdoor_temps)
    
    # Output JSONL records to stdout
    for obs in observations:
        print(json.dumps(obs))


if __name__ == "__main__":
    main()
