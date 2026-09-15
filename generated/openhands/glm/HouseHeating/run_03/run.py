#!/usr/bin/env python3
"""
House Heating Temperature Control Simulation

A discrete-event simulation of a bang-bang heater controlling room temperature.
The system models heat loss to the outdoor environment and heater gain.
"""

import argparse
import json
import sys
from typing import Dict, List, Tuple


def parse_time_to_seconds(time_str: str) -> int:
    """Convert HH:MM:SS format to total seconds."""
    hours, minutes, seconds = map(int, time_str.split(':'))
    return hours * 3600 + minutes * 60 + seconds


def read_outdoor_temperatures() -> List[Tuple[int, float]]:
    """
    Read outdoor temperature schedule from stdin.
    
    Returns:
        List of (timestamp_seconds, temperature) tuples sorted by timestamp.
    """
    temperatures = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            time_str = parts[0]
            temp = float(parts[1])
            timestamp = parse_time_to_seconds(time_str)
            temperatures.append((timestamp, temp))
    
    # Sort by timestamp
    temperatures.sort(key=lambda x: x[0])
    return temperatures


def get_outdoor_temperature(temperatures: List[Tuple[int, float]], time_sec: int) -> float:
    """
    Get the outdoor temperature at a given simulation time.
    
    Uses the reading with the greatest timestamp less than or equal to time_sec.
    If no such reading exists, returns 25.0.
    
    Args:
        temperatures: List of (timestamp, temperature) tuples
        time_sec: Current simulation time in seconds
        
    Returns:
        Outdoor temperature at the given time
    """
    # Find the greatest timestamp <= time_sec
    best_temp = 25.0
    for timestamp, temp in temperatures:
        if timestamp <= time_sec:
            best_temp = temp
        else:
            break
    return best_temp


def simulate_heating_system(simulate_time: float, outdoor_temps: List[Tuple[int, float]]):
    """
    Simulate the house heating system using discrete-event simulation.
    
    Args:
        simulate_time: Total simulation duration in seconds
        outdoor_temps: List of (timestamp, temperature) tuples for outdoor temps
    """
    # Initial state at time 0
    room_temp_c = 25.0
    control_signal = 0
    heater_output_c = 0.0
    
    # Simulate for each integer second from 1 to int(simulate_time)
    num_steps = int(simulate_time)
    
    for t in range(1, num_steps + 1):
        # Get outdoor temperature at previous time step (t-1)
        outdoor_temp = get_outdoor_temperature(outdoor_temps, t - 1)
        
        # Cap outdoor temperature to not exceed room temperature
        # This prevents outdoor heat gain
        effective_outdoor_temp = min(outdoor_temp, room_temp_c)
        
        # Apply heat loss: room loses 10% of the gap between its temperature
        # and the effective outdoor temperature
        temp_gap = room_temp_c - effective_outdoor_temp
        heat_loss = 0.1 * temp_gap
        heat_loss_temp_c = room_temp_c - heat_loss
        
        # Heater gain is delayed by one step
        # Heater adds 0.5 degrees if previous control signal was 1
        heater_output_c = 0.5 if control_signal == 1 else 0.0
        
        # New room temperature is heat-loss value plus heater gain
        room_temp_c = heat_loss_temp_c + heater_output_c
        
        # Output the observable state for this time step
        # control_signal is the signal used for the heater at this step
        state = {
            "time_sec": t,
            "room_temp_c": round(room_temp_c, 6),
            "heat_loss_temp_c": round(heat_loss_temp_c, 6),
            "control_signal": control_signal,
            "heater_output_c": heater_output_c
        }
        
        print(json.dumps(state))
        
        # Set next control signal based on new room temperature
        # Heater should be on (1) when room is below 24.9, otherwise off (0)
        control_signal = 1 if room_temp_c < 24.9 else 0


def main():
    """Main entry point for the simulation."""
    parser = argparse.ArgumentParser(
        description='Simulate house heating temperature control system'
    )
    parser.add_argument(
        '--simulate_time',
        type=float,
        required=True,
        help='Total simulation duration in seconds'
    )
    
    args = parser.parse_args()
    
    # Read outdoor temperature schedule from stdin
    outdoor_temps = read_outdoor_temperatures()
    
    # Run the simulation
    simulate_heating_system(args.simulate_time, outdoor_temps)


if __name__ == '__main__':
    main()
