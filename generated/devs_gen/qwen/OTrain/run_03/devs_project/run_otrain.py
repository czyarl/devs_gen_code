import argparse
import sys
import json
import logging
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock, get_current_time

# The evaluator launches this runner with ``python -m package.runner``.
# The leading dot keeps the model import inside that generated package.
from .OTrain import OTrain

def parse_time_format(time_str):
    """Parse time string in HH:MM:SS:mmm format to seconds."""
    h, m, s, ms = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s + ms / 1000.0

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run OTrain simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--simulate_time", type=str, default="00:01:00:000", help="Simulation duration in HH:MM:SS:mmm format")
    
    args = parser.parse_args()
    
    # Parse simulate_time
    simulate_time = parse_time_format(args.simulate_time)
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    model = OTrain( # instance the model
        name="OTrain", 
        parent=None,
        simulate_time=args.simulate_time
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # Run simulation for the specified time
    sim.simulate_time(simulate_time)
    sim.exit()
    ### END