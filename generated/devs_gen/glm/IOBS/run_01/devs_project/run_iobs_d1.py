import argparse
import random
import time
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

from .IOBS_D1 import IOBS_D1

if __name__ == "__main__":
    # Use system time to set the seed for random number generation
    random.seed(time.time_ns())

    parser = argparse.ArgumentParser(description="Run IOBS_D1 simulation")
    
    # Argument for simulation duration
    parser.add_argument("--simulation_time", type=float, default=1000000.0, help="Total simulation time in seconds")
    
    args = parser.parse_args()
    
    # Initialization
    clock = SimulationClock()
    set_global_clock(clock)
    
    # Instantiate the model with name and parent as per registry
    model = IOBS_D1(name="IOBS_D1", parent=None)
    
    sim = Coordinator(model, clock)
    
    # Simulation Execution
    sim.initialize()
    # Advance by a tiny amount to include events exactly at the boundary
    sim.simulate_time(args.simulation_time + 1e-9)
    sim.exit()