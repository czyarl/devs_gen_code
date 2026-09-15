import argparse
import json
import logging
import random
import sys
import time
from collections import defaultdict
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .OTrain import OTrain

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run OTrain simulation")
    parser.add_argument("--simulate_time", type=str, default="00:01:00:000", help="Simulation duration in HH:MM:SS:mmm")
    
    args = parser.parse_args()
    
    # Parse simulate_time
    hours, minutes, seconds, millis = args.simulate_time.split(":")
    simulate_time = int(hours)*3600 + int(minutes)*60 + int(seconds) + int(millis)/1000
    
    # Initialize the clock and set it globally
    clock = SimulationClock()
    set_global_clock(clock)
    
    # Instantiate the model
    model = OTrain(
        name="OTrain",
        parent=None,
        simulate_time=args.simulate_time
    )
    
    # Create the simulator
    sim = Coordinator(model, clock)
    
    # Initialize and run the simulation
    sim.initialize()
    sim.simulate_time(simulate_time)
    sim.exit()