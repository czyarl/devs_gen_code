#!/usr/bin/env python3
"""
House Heating Temperature Control Simulation

A discrete event simulation of a bang-bang heater controlling room temperature.
The system models heat loss to outdoor environment and heater gain with
one-step delay in control signal.
"""

import argparse
import json
import sys
from typing import Dict, List, Tuple


def parse_time_to_seconds(time_str: str) -> int:
    """Convert HH:MM:SS format to total seconds."""
    parts = time_str.split(':')
    if len(parts) != 3:
        raise ValueError(f"Invalid time format: {time_str}")
    hours, minutes, seconds = map(int, parts)
    return hours * 3600 + minutes * 60 + seconds


def read_outdoor_temperatures() -> List[Tuple[int, float]]:
    """Read outdoor temperature schedule from stdin.
    
    Returns:
        List of (timestamp_seconds, temperature) tuples sorted by timestamp.
    """
    readings = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            continue
        time_str, temp_str = parts
        try:
            timestamp = parse_time_to_seconds(time_str)
            temperature = float(temp_str)
            readings.append((timestamp, temperature))
        except (ValueError, IndexError):
            continue
    readings.sort(key=lambda x: x[0])
    return readings


def get_outdoor_temperature(readings: List[Tuple[int, float]], time_sec: int) -> float:
    """Get outdoor temperature at a given simulation time.
    
    Uses the reading with greatest timestamp <= time_sec.
    If no such reading exists, returns 25.0.
    """
    if not readings:
        return 25.0
    
    # Find the greatest timestamp <= time_sec
    for timestamp, temp in reversed(readings):
        if timestamp <= time_sec:
            return temp
    
    return 25.0


class HeatingSimulation:
    """Discrete event simulation of house heating system."""
    
    def __init__(self, simulate_time: float, outdoor_readings: List[Tuple[int, float]]):
        self.simulate_time = int(simulate_time)
        self.outdoor_readings = outdoor_readings
        
        # Initial state at time 0
        self.room_temp = 25.0
        self.control_signal = 0
        self.heater_output = 0.0
        
        # Target temperature for controller
        self.target_temp = 24.9
        
        # Store previous control signal for delayed heater gain
        self.prev_control_signal = 0
    
    def step(self, time_sec: int) -> Dict:
        """Execute one simulation step at time_sec.
        
        Returns:
            Dictionary with observable state for this time step.
        """
        # Get outdoor temperature for previous second
        outdoor_temp = get_outdoor_temperature(self.outdoor_readings, time_sec - 1)
        
        # Cap outdoor temperature to previous room temperature
        # (prevents outdoor heat gain)
        effective_outdoor_temp = min(outdoor_temp, self.room_temp)
        
        # Apply heat loss: lose 10% of gap between room temp and effective outdoor temp
        temp_gap = self.room_temp - effective_outdoor_temp
        heat_loss = 0.1 * temp_gap
        heat_loss_temp = self.room_temp - heat_loss
        
        # Apply heater gain (delayed by one step)
        # Heater adds 0.5 degrees if previous control signal was 1
        heater_gain = 0.5 if self.prev_control_signal == 1 else 0.0
        self.heater_output = heater_gain
        
        # Update room temperature
        self.room_temp = heat_loss_temp + heater_gain
        
        # Store current control signal for next step's heater gain
        self.prev_control_signal = self.control_signal
        
        # Determine next control signal based on new room temperature
        # Heater on (1) if room below target, off (0) otherwise
        self.control_signal = 1 if self.room_temp < self.target_temp else 0
        
        # Return observable state
        return {
            "time_sec": time_sec,
            "room_temp_c": round(self.room_temp, 6),
            "heat_loss_temp_c": round(heat_loss_temp, 6),
            "control_signal": self.control_signal,
            "heater_output_c": round(self.heater_output, 6)
        }
    
    def run(self):
        """Run the complete simulation and output JSONL records."""
        # Output observations for seconds 1 through simulate_time
        for time_sec in range(1, self.simulate_time + 1):
            state = self.step(time_sec)
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
    outdoor_readings = read_outdoor_temperatures()
    
    # Run simulation
    sim = HeatingSimulation(args.simulate_time, outdoor_readings)
    sim.run()


if __name__ == "__main__":
    main()
