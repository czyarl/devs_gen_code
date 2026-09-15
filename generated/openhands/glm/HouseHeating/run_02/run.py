#!/usr/bin/env python3
"""
House Heating Temperature Control Simulation

A discrete-event simulation of a single heated room controlled by a bang-bang heater.
The system models heat loss to outdoor temperature and heater gain to maintain
a target temperature of 24.9 degrees Celsius.
"""

import argparse
import sys
import json
from typing import Dict, List, Tuple


def parse_outdoor_temperatures() -> Dict[int, float]:
    """
    Parse outdoor temperature schedule from stdin.
    
    Returns:
        Dictionary mapping timestamp (seconds) to outdoor temperature (Celsius).
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
            # Parse HH:MM:SS format to seconds
            h, m, s = map(int, time_str.split(':'))
            timestamp = h * 3600 + m * 60 + s
            outdoor_temps[timestamp] = temp
    return outdoor_temps


def get_outdoor_temperature(t: int, outdoor_temps: Dict[int, float]) -> float:
    """
    Get outdoor temperature at simulation time t.
    
    Uses the reading with the greatest timestamp less than or equal to t.
    If no such reading exists, returns 25.0.
    
    Args:
        t: Current simulation time in seconds.
        outdoor_temps: Dictionary of timestamped outdoor temperatures.
    
    Returns:
        Outdoor temperature in Celsius.
    """
    valid_timestamps = [ts for ts in outdoor_temps.keys() if ts <= t]
    if not valid_timestamps:
        return 25.0
    latest_timestamp = max(valid_timestamps)
    return outdoor_temps[latest_timestamp]


def simulate_house_heating(simulate_time: float, outdoor_temps: Dict[int, float]):
    """
    Run the house heating simulation.
    
    Args:
        simulate_time: Total simulation duration in seconds.
        outdoor_temps: Dictionary of timestamped outdoor temperatures.
    """
    # Initial state at time 0
    room_temp = 25.0
    control_signal = 0
    heater_output = 0.0
    
    # Output observations for each integer second from 1 to int(simulate_time)
    for t in range(1, int(simulate_time) + 1):
        # Get outdoor temperature for previous second
        outdoor_temp = get_outdoor_temperature(t - 1, outdoor_temps)
        
        # Cap outdoor temperature to previous room temperature
        effective_outdoor_temp = min(outdoor_temp, room_temp)
        
        # Calculate heat loss: room loses 10% of the gap between its temperature
        # and the effective outdoor temperature
        temp_gap = room_temp - effective_outdoor_temp
        heat_loss_temp = room_temp - 0.1 * temp_gap
        
        # Heater gain is delayed by one step: adds 0.5 degrees if previous
        # control signal was 1, otherwise adds 0.0
        heater_output = 0.5 if control_signal == 1 else 0.0
        
        # New room temperature is heat-loss value plus heater gain
        new_room_temp = heat_loss_temp + heater_output
        
        # Record the observation
        observation = {
            "time_sec": t,
            "room_temp_c": new_room_temp,
            "heat_loss_temp_c": heat_loss_temp,
            "control_signal": control_signal,
            "heater_output_c": heater_output
        }
        print(json.dumps(observation))
        
        # Update state for next iteration
        room_temp = new_room_temp
        
        # Controller sets next control signal: 1 when room is below 24.9, else 0
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
    
    # Parse outdoor temperature schedule from stdin
    outdoor_temps = parse_outdoor_temperatures()
    
    # Run the simulation
    simulate_house_heating(args.simulate_time, outdoor_temps)


if __name__ == "__main__":
    main()
