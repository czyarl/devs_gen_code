### BEGIN: General Import
import argparse
import time
import random
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
### END

# The evaluator launches this runner with ``python -m package.runner``.
# The leading dot keeps the model import inside that generated package.
### BEGIN: Model import, must be relative
from .OTrain import OTrain
### END

if __name__ == "__main__":
    # Set random seed using system time as requested
    random.seed(time.time_ns())

    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run OTrain simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument(
        "--simulate_time", 
        type=str, 
        default="00:01:00:000", 
        help="Simulation duration in 'HH:MM:SS:mmm' format"
    )
    
    args = parser.parse_args()
    
    # Parse the time string "HH:MM:SS:mmm" to float seconds
    time_str = args.simulate_time
    try:
        parts = list(map(int, time_str.split(':')))
        # Expecting HH, MM, SS, mmm
        if len(parts) == 4:
            h, m, s, ms = parts
            simulate_time = h * 3600 + m * 60 + s + ms / 1000.0
        else:
            # Fallback if format is unexpected, treat as seconds if possible
            simulate_time = float(time_str)
    except ValueError:
        # Fallback to default 60 seconds if parsing fails
        simulate_time = 60.0
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    # Instantiate the model with required init args: name and parent
    model = OTrain(
        name="OTrain", 
        parent=None
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # Add a tiny epsilon to ensure events exactly at the boundary are processed
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()
    ### END