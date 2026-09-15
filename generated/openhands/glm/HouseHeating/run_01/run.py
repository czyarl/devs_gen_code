#!/usr/bin/env python3
"""
House Heating Temperature Control Simulation

A discrete-event simulation of a bang-bang heater controlling room temperature.
"""

import argparse
import json
import sys
from typing import Dict, List, Tuple


def parse_time_to_seconds(time_str: str) -> int:
    """Convert HH:MM:SS format to seconds."""
    parts = time_str.split(':')
    if len(parts) != 3:
        raise ValueError(f"Invalid time format: {time_str}")
    hours, minutes, seconds = map(int, parts)
    return hours * 3600 + minutes * 60 + seconds


def read_outdoor_temperatures() -> Dict[int, float]:
    """Read outdoor temperature schedule from stdin.
    
    Returns a dictionary mapping timestamp (seconds) to temperature.
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
        time_str, temp_str = parts
        try:
            timestamp = parse_time_to_seconds(time_str)
            temp = float(temp_str)
            outdoor_temps[timestamp] = temp
        except (ValueError, IndexError) as e:
            print(f"Warning: Skipping invalid line: {line} ({e})", file=sys.stderr)
            continue
    return outdoor_temps


def get_outdoor_temperature(outdoor_temps: Dict[int, float], time_sec: int) -> float:
    """Get outdoor temperature at a given time.
    
    Uses the reading with the greatest timestamp <= time_sec.
    If no such reading exists, returns 25.0.
    """
    valid_timestamps = [ts for ts in outdoor_temps.keys() if ts <= time_sec]
    if not valid_timestamps:
        return 25.0
    latest_timestamp = max(valid_timestamps)
    return outdoor_temps[latest_timestamp]


class HouseHeatingSimulation:
    """Simulates the house heating temperature control system."""
    
    def __init__(self, simulate_time: float, outdoor_temps: Dict[int, float]):
        self.simulate_time = int(simulate_time)
        self.outdoor_temps = outdoor_temps
        
        # Initial state at time 0
        self.room_temp_c = 25.0
        self.control_signal = 0
        self.heater_output_c = 0.0
        
    def run(self):
        """Run the simulation and output JSONL records."""
        for t in range(1, self.simulate_time + 1):
            # Get outdoor temperature for previous second
            outdoor_temp = get_outdoor_temperature(self.outdoor_temps, t - 1)
            
            # Cap outdoor temperature to previous room temperature
            effective_outdoor_temp = min(outdoor_temp, self.room_temp_c)
            
            # Apply heat loss: lose 10% of the gap
            temp_gap = self.room_temp_c - effective_outdoor_temp
            heat_loss_temp_c = self.room_temp_c - (0.1 * temp_gap)
            
            # Apply heater gain (delayed by one step)
            heater_output_c = 0.5 if self.control_signal == 1 else 0.0
            
            # Calculate new room temperature
            new_room_temp_c = heat_loss_temp_c + heater_output_c
            
            # Update control signal for next step
            new_control_signal = 1 if new_room_temp_c < 24.9 else 0
            
            # Output observation
            observation = {
                "time_sec": t,
                "room_temp_c": round(new_room_temp_c, 6),
                "heat_loss_temp_c": round(heat_loss_temp_c, 6),
                "control_signal": new_control_signal,
                "heater_output_c": round(heater_output_c, 6)
            }
            print(json.dumps(observation))
            
            # Update state for next iteration
            self.room_temp_c = new_room_temp_c
            self.control_signal = new_control_signal
            self.heater_output_c = heater_output_c


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
    simulation = HouseHeatingSimulation(args.simulate_time, outdoor_temps)
    simulation.run()


if __name__ == "__main__":
    main()
