### BEGIN: General Import
import argparse
import json
import logging
import sys
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .OTrain import OTrain
### END

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run OTrain simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--simulate_time", type=str, default="00:01:00:000", help="Simulation duration in HH:MM:SS:mmm format")
    
    args = parser.parse_args()
    
    # Convert simulation time from "HH:MM:SS:mmm" format to seconds
    simulate_time_parts = args.simulate_time.split(":")
    simulate_time = int(simulate_time_parts[0]) * 3600 + int(simulate_time_parts[1]) * 60 + int(simulate_time_parts[2]) + int(simulate_time_parts[3]) / 1000
    ### END

    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    model = OTrain( # instance the model
        name="OTrain", 
        parent=None
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    sim.simulate_time(simulate_time)
    sim.exit()
    
    # Print final state to stdout
    final_state = {
        "time": sim.get_current_time(),
        "event": "simulation_end",
        "entity_type": "OTrain",
        "station_id": None,
        "station": None,
        "payload": {}
    }
    print(json.dumps(final_state))
    ### END