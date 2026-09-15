import argparse
import random
import time

from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with ``python -m package.runner``.
# The leading dot keeps the model import inside that generated package.
from .IOBS_D1 import IOBS_D1

if __name__ == "__main__":
    # Set random seed based on system time as requested
    random.seed(time.time_ns())

    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run IOBS_D1 simulation")
    
    # Define arguments based on the Simulation Scenario
    parser.add_argument("--simulation_time", type=float, default=1000000.0, help="Total simulation time in seconds")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity
    simulation_time = args.simulation_time
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    # Instantiate the model IOBS_D1
    # The model specification requires 'name' and 'parent'.
    # We use the class name for the instance name and None for the parent (root model).
    model = IOBS_D1(
        name="IOBS_D1", 
        parent=None
    )
    
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    
    # Run simulation for the specified duration.
    # Adding a tiny epsilon to ensure events exactly at the boundary are processed,
    # as xDEVS stops strictly before the requested time bound.
    sim.simulate_time(simulation_time + 1e-9)
    
    sim.exit()
    ### END