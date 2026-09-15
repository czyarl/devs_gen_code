import argparse
import json
import logging
import random
import sys
import time
from collections import defaultdict
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock, get_current_time
from .IOBS_D1 import IOBS_D1

def main():
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run IOBS_D1 simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--simulation_time", type=float, default=1000000.0, help="Total simulation time in seconds")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity (optional, can use args.x directly)
    simulation_time = args.simulation_time
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    model = IOBS_D1( # instance the model
        name="IOBS_D1", 
        parent=None,
        simulation_time=simulation_time
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    sim.simulate_time(simulation_time)
    sim.exit()
    ### END

if __name__ == "__main__":
    main()