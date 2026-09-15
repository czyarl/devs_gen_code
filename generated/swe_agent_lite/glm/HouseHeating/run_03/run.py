#!/usr/bin/env python3
"""
House Heating Temperature Control Simulation

A discrete-event simulation of a single heated room controlled by a bang-bang heater.
The system models heat loss to outdoor temperature and heater gain to maintain
a target temperature of 24.9 degrees Celsius.
"""

import argparse
import json
import sys
from typing import Dict, List, Tuple


def parse_time_to_seconds(time_str: str) -> int:
    """
    Parse a time string in HH:MM:SS format to total seconds.
    
    Args:
        time_str: Time string in format "HH:MM:SS"
        
    Returns:
        Total seconds as integer
    """
    parts = time_str.strip().split(':')
    if len(parts) != 3:
        raise ValueError(f"Invalid time format: {time_str}")
    
    hours, minutes, seconds = map(int, parts)
    return hours * 3600 + minutes * 60 + seconds


def read_outdoor_temperature_schedule() -> List[Tuple[int, float]]:
    """
    Read outdoor temperature schedule from stdin.
    
    Each non-empty line contains a timestamp in HH:MM:SS format followed by
    one numeric outdoor temperature.
    
    Returns:
        List of (timestamp_seconds, temperature) tuples, sorted by timestamp
    """
    schedule = []
    
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split()
        if len(parts) < 2:
            continue
        
        time_str = parts[0]
        temp_str = parts[1]
        
        try:
            timestamp = parse_time_to_seconds(time_str)
            temperature = float(temp_str)
            schedule.append((timestamp, temperature))
        except (ValueError, IndexError) as e:
            print(f"Warning: Skipping invalid line: {line} ({e})", file=sys.stderr)
    
    # Sort by timestamp
    schedule.sort(key=lambda x: x[0])
    return schedule


def get_outdoor_temperature(
    schedule: List[Tuple[int, float]], 
    time_sec: int
) -> float:
    """
    Get the outdoor temperature at a given simulation time.
    
    For any simulation time t, use the reading with the greatest timestamp
    less than or equal to t. If there is no such reading, use 25.0.
    
    Args:
        schedule: List of (timestamp, temperature) tuples
        time_sec: Current simulation time in seconds
        
    Returns:
        Outdoor temperature at the given time
    """
    # Find the greatest timestamp <= time_sec
    best_temp = 25.0  # Default temperature
    
    for timestamp, temp in schedule:
        if timestamp <= time_sec:
            best_temp = temp
        else:
            break
    
    return best_temp


class HeatingSimulation:
    """
    Discrete-time simulation of a house heating system.
    """
    
    def __init__(self, simulate_time: float, outdoor_schedule: List[Tuple[int, float]]):
        """
        Initialize the simulation.
        
        Args:
            simulate_time: Total simulation duration in seconds
            outdoor_schedule: List of (timestamp, temperature) tuples for outdoor temps
        """
        self.simulate_time = int(simulate_time)
        self.outdoor_schedule = outdoor_schedule
        
        # Initial state at time 0
        self.room_temp_c = 25.0
        self.control_signal = 0
        self.heater_output_c = 0.0
        
    def step(self, t: int) -> Dict:
        """
        Perform one simulation step at time t.
        
        Args:
            t: Current simulation time (integer seconds)
            
        Returns:
            Dictionary containing the observable state at time t
        """
        # Get outdoor temperature for the previous second (t-1)
        # The dynamics use the outdoor temperature from the previous step
        outdoor_temp = get_outdoor_temperature(self.outdoor_schedule, t - 1)
        
        # Cap outdoor temperature to previous room temperature
        # This prevents outdoor heat gain
        effective_outdoor_temp = min(outdoor_temp, self.room_temp_c)
        
        # Apply heat loss: room loses 10% of the gap between its previous temperature
        # and the effective outdoor temperature
        temp_gap = self.room_temp_c - effective_outdoor_temp
        heat_loss_temp_c = self.room_temp_c - (0.1 * temp_gap)
        
        # Heater gain is delayed by one step: the heater adds 0.5 degrees during
        # the current step only if the previous control signal was 1
        heater_output_c = 0.5 if self.control_signal == 1 else 0.0
        
        # New room temperature is the heat-loss value plus heater gain
        new_room_temp_c = heat_loss_temp_c + heater_output_c
        
        # Store the heater output for observation
        self.heater_output_c = heater_output_c
        
        # Store the heat loss temperature for observation
        self.heat_loss_temp_c = heat_loss_temp_c
        
        # Update room temperature
        self.room_temp_c = new_room_temp_c
        
        # Controller sets the next control signal
        # Set to 1 when room is below 24.9 degrees, otherwise 0
        new_control_signal = 1 if self.room_temp_c < 24.9 else 0
        
        # Store the control signal for observation (this is the signal that was
        # used for this step, i.e., the previous signal)
        observed_control_signal = self.control_signal
        
        # Update control signal for next step
        self.control_signal = new_control_signal
        
        # Return observable state
        return {
            "time_sec": t,
            "room_temp_c": round(self.room_temp_c, 6),
            "heat_loss_temp_c": round(self.heat_loss_temp_c, 6),
            "control_signal": observed_control_signal,
            "heater_output_c": round(self.heater_output_c, 6)
        }
    
    def run(self):
        """
        Run the simulation and output JSONL records to stdout.
        """
        # Output observations for seconds 1 through simulate_time
        for t in range(1, self.simulate_time + 1):
            state = self.step(t)
            print(json.dumps(state))


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
    outdoor_schedule = read_outdoor_temperature_schedule()
    
    # Create and run simulation
    sim = HeatingSimulation(args.simulate_time, outdoor_schedule)
    sim.run()


if __name__ == "__main__":
    main()
