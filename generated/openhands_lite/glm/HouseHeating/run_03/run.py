#!/usr/bin/env python3
"""
House Heating Temperature Control Simulation

A discrete event simulation of a bang-bang heater controlling room temperature.
"""

import argparse
import json
import sys
from typing import Dict, List, Tuple


def parse_time_to_seconds(time_str: str) -> int:
    """Convert HH:MM:SS format to total seconds."""
    hours, minutes, seconds = map(int, time_str.split(':'))
    return hours * 3600 + minutes * 60 + seconds


def read_outdoor_temperatures() -> Dict[int, float]:
    """
    Read outdoor temperature schedule from stdin.
    
    Returns:
        Dictionary mapping timestamp (seconds) to outdoor temperature.
    """
    outdoor_temps = {}
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            time_str = parts[0]
            temp = float(parts[1])
            timestamp = parse_time_to_seconds(time_str)
            outdoor_temps[timestamp] = temp
    return outdoor_temps


def get_outdoor_temperature(outdoor_temps: Dict[int, float], time_sec: int) -> float:
    """
    Get outdoor temperature at a given simulation time.
    
    Uses the reading with the greatest timestamp <= time_sec.
    If no such reading exists, returns 25.0.
    
    Args:
        outdoor_temps: Dictionary of timestamp -> temperature
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


def simulate_heating_system(simulate_time: float, outdoor_temps: Dict[int, float]) -> List[Dict]:
    """
    Simulate the house heating system using discrete event simulation.
    
    Args:
        simulate_time: Total simulation duration in seconds
        outdoor_temps: Dictionary mapping timestamps to outdoor temperatures
        
    Returns:
        List of observation dictionaries for each integer second
    """
    observations = []
    
    # Initial state at time 0
    room_temp = 25.0
    control_signal = 0
    heater_output = 0.0
    
    # Simulate for each integer second from 1 to int(simulate_time)
    num_steps = int(simulate_time)
    for t in range(1, num_steps + 1):
        # Get outdoor temperature for the previous time step (t-1)
        outdoor_temp = get_outdoor_temperature(outdoor_temps, t - 1)
        
        # Cap outdoor temperature to current room temperature
        # This prevents outdoor heat gain
        effective_outdoor_temp = min(outdoor_temp, room_temp)
        
        # Apply heat loss: room loses 10% of the gap between room temp and effective outdoor temp
        temp_gap = room_temp - effective_outdoor_temp
        heat_loss = 0.1 * temp_gap
        heat_loss_temp = room_temp - heat_loss
        
        # Heater gain is delayed by one step
        # Heater adds 0.5 degrees if previous control_signal was 1, else 0.0
        heater_output = 0.5 if control_signal == 1 else 0.0
        
        # New room temperature
        new_room_temp = heat_loss_temp + heater_output
        
        # Set next control signal: 1 if room is below 24.9, else 0
        new_control_signal = 1 if new_room_temp < 24.9 else 0
        
        # Create observation record
        observation = {
            "time_sec": t,
            "room_temp_c": round(new_room_temp, 6),
            "heat_loss_temp_c": round(heat_loss_temp, 6),
            "control_signal": new_control_signal,
            "heater_output_c": round(heater_output, 6)
        }
        observations.append(observation)
        
        # Update state for next iteration
        room_temp = new_room_temp
        control_signal = new_control_signal
    
    return observations


def main():
    """Main entry point for the simulation."""
    parser = argparse.ArgumentParser(
        description="Simulate house heating temperature control system"
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
    
    # Run the simulation
    observations = simulate_heating_system(args.simulate_time, outdoor_temps)
    
    # Output observations as JSONL
    for obs in observations:
        print(json.dumps(obs))


if __name__ == "__main__":
    main()
