#!/usr/bin/env python3
"""House Heating Temperature Control Simulation using Discrete Event Simulation."""

import argparse
import json
import sys
import simpy
from typing import Dict, List, Tuple


def parse_time_to_seconds(time_str: str) -> int:
    """Convert HH:MM:SS format to total seconds."""
    parts = time_str.split(':')
    hours, minutes, seconds = int(parts[0]), int(parts[1]), int(parts[2])
    return hours * 3600 + minutes * 60 + seconds


def parse_outdoor_temperatures() -> List[Tuple[int, float]]:
    """Parse outdoor temperature readings from stdin.
    
    Returns:
        List of (timestamp_seconds, temperature) tuples sorted by timestamp.
    """
    readings = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            time_str = parts[0]
            temp = float(parts[1])
            timestamp = parse_time_to_seconds(time_str)
            readings.append((timestamp, temp))
    
    # Sort by timestamp
    readings.sort(key=lambda x: x[0])
    return readings


def get_outdoor_temperature(time_sec: int, readings: List[Tuple[int, float]]) -> float:
    """Get outdoor temperature for a given simulation time.
    
    Uses the reading with the greatest timestamp <= time_sec.
    If no such reading exists, returns 25.0.
    """
    for timestamp, temp in reversed(readings):
        if timestamp <= time_sec:
            return temp
    return 25.0


class HouseHeatingSystem:
    """House heating system using discrete event simulation."""
    
    def __init__(self, env: simpy.Environment, outdoor_readings: List[Tuple[int, float]]):
        self.env = env
        self.outdoor_readings = outdoor_readings
        
        # Initial state at time 0
        self.room_temp_c = 25.0
        self.control_signal = 0
        self.heater_output_c = 0.0
        
        # Observable states
        self.observations = []
    
    def update_temperature(self):
        """Update temperature dynamics at each time step."""
        while True:
            # Store previous state for calculations
            prev_room_temp = self.room_temp_c
            prev_control_signal = self.control_signal
            
            # Get outdoor temperature for current time
            outdoor_temp = get_outdoor_temperature(int(self.env.now), self.outdoor_readings)
            
            # Cap outdoor temperature to previous room temperature
            effective_outdoor_temp = min(outdoor_temp, prev_room_temp)
            
            # Apply heat loss: room loses 10% of the gap to effective outdoor temperature
            heat_loss_temp_c = prev_room_temp - 0.1 * (prev_room_temp - effective_outdoor_temp)
            
            # Apply heater gain (delayed by one step)
            heater_output_c = 0.5 if prev_control_signal == 1 else 0.0
            
            # Calculate new room temperature
            self.room_temp_c = heat_loss_temp_c + heater_output_c
            
            # Set next control signal based on new room temperature
            self.control_signal = 1 if self.room_temp_c < 24.9 else 0
            
            # Record observable state
            state = {
                "time_sec": int(self.env.now),
                "room_temp_c": round(self.room_temp_c, 6),
                "heat_loss_temp_c": round(heat_loss_temp_c, 6),
                "control_signal": self.control_signal,
                "heater_output_c": round(heater_output_c, 6)
            }
            self.observations.append(state)
            
            # Wait for next time step
            yield self.env.timeout(1)


def run_simulation(simulate_time: float, outdoor_readings: List[Tuple[int, float]]):
    """Run the discrete event simulation."""
    # Create simpy environment
    env = simpy.Environment()
    
    # Create house heating system
    system = HouseHeatingSystem(env, outdoor_readings)
    
    # Add temperature update process
    env.process(system.update_temperature())
    
    # Run simulation
    env.run(until=simulate_time)
    
    # Output observations for time >= 1
    for state in system.observations:
        if state["time_sec"] >= 1:
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
    
    # Parse outdoor temperature readings from stdin
    outdoor_readings = parse_outdoor_temperatures()
    
    # Run simulation
    run_simulation(args.simulate_time, outdoor_readings)


if __name__ == "__main__":
    main()
