### BEGIN: General Import
import argparse
import json
import logging
import random
import sys
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock, get_current_time
### END

### BEGIN: Model import, must be relative
from .OTrain import OTrain
### END

def main():
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run OTrain simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--simulate_time", type=str, default="00:01:00:000", help="Simulation duration")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity (optional, can use args.x directly)
    simulate_time = args.simulate_time
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    model = OTrain( # instance the model
        name="OTrain", 
        parent=None,
        simulate_time=simulate_time
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    sim.simulate_time(simulate_time)
    sim.exit()
    
    ### END
    return 0

if __name__ == "__main__":
    random.seed(sys.time_ns())
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    main()