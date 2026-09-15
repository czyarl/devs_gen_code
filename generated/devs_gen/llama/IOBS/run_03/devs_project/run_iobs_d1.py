import argparse
import json
import logging
import sys
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .IOBS_D1 import IOBS_D1

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run IOBS_D1 simulation")
    
    parser.add_argument("--simulation_time", type=float, default=1000000.0, help="Simulation duration")
    
    args = parser.parse_args()
    
    simulation_time = args.simulation_time
    
    clock = SimulationClock()
    set_global_clock(clock)
    
    model = IOBS_D1(
        name="IOBS_D1", 
        parent=None,
        simulation_time=simulation_time
    )
    sim = Coordinator(model, clock)
    
    sim.initialize()
    sim.simulate_time(simulation_time)
    sim.exit()