### BEGIN: General Import
import argparse
import time
import random
import numpy as np
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
### END

# The evaluator launches this runner with ``python -m package.runner``.
# The leading dot keeps the model import inside that generated package.
### BEGIN: Model import, must be relative
from .OTrain import OTrain
### END

def parse_duration(duration_str):
    """
    Parses a duration string in HH:MM:SS:mmm format to seconds (float).
    """
    parts = duration_str.split(':')
    if len(parts) != 4:
        raise ValueError(f"Invalid duration format: {duration_str}. Expected HH:MM:SS:mmm")
    
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run OTrain simulation")
    
    # Model initialization arguments based on System Registry
    parser.add_argument("--name", type=str, default="OTrain", help="Model instance name")
    
    # Scenario-specific arguments
    parser.add_argument("--simulate_time", type=str, default="00:01:00:000", 
                        help="Simulation duration in HH:MM:SS:mmm")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity
    model_name = args.name
    simulate_time_str = args.simulate_time
    
    ### BEGIN: Initialization
    
    # Set random seeds using system time as required
    current_time_ns = time.time_ns()
    random.seed(current_time_ns)
    np.random.seed(current_time_ns % (2**32 - 1))
    
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    # Instantiate the model
    # Note: 'parent' is None for the root model
    model = OTrain(
        name=model_name,
        parent=None
    )
    
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    
    # Parse the simulation time string to numeric seconds
    duration_seconds = parse_duration(simulate_time_str)
    
    # Run simulation. 
    # Adding a tiny epsilon to ensure events exactly at the boundary are processed 
    # if the scenario implies an inclusive observation horizon.
    sim.simulate_time(duration_seconds + 1e-9)
    
    sim.exit()
    ### END