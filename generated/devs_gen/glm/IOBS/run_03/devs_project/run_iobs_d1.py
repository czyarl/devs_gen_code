import argparse
import random
import time

# Attempt to import numpy as requested for seeding, handle gracefully if missing
try:
    import numpy
except ImportError:
    numpy = None

from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# Relative import for the target model
from .IOBS_D1 import IOBS_D1

if __name__ == "__main__":
    # Seed random number generators using system time as requested
    random.seed(time.time_ns())
    if numpy is not None:
        numpy.random.seed(time.time_ns() % (2**32 - 1))

    # Configuration using ArgParse
    parser = argparse.ArgumentParser(description="Run IOBS_D1 simulation")
    
    # Define arguments based on Simulation Scenario
    parser.add_argument(
        "--simulation_time", 
        type=float, 
        default=1000000.0, 
        help="Total simulation time in seconds"
    )
    
    args = parser.parse_args()
    
    # Extract simulation time
    simulation_time = args.simulation_time

    # Initialization
    clock = SimulationClock()
    set_global_clock(clock)
    
    # Instantiate the root model
    # Model specification defines 'name' and 'parent' as init args.
    # We hardcode these for the root model instance.
    model = IOBS_D1(
        name="IOBS_D1",
        parent=None
    )
    
    # Create the Simulator (Coordinator)
    sim = Coordinator(model, clock)
    
    # Simulation Execution
    sim.initialize()
    
    # Run simulation.
    # xDEVS stops before an event exactly at the requested bound, so we advance
    # by a tiny epsilon to ensure boundary events are processed if they exist.
    sim.simulate_time(simulation_time + 1e-9)
    
    sim.exit()