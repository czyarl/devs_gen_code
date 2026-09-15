### BEGIN: General Import
import argparse
import json
import sys
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock, get_current_time
### END

### BEGIN: Model import, must be relative
from .Barbershop_D1 import Barbershop_D1
### END

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run Barbershop_D1 simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--simulation_time", type=float, default=1000000.0, help="Simulation duration")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity (optional, can use args.x directly)
    simulation_time = args.simulation_time
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    model = Barbershop_D1( # instance the model
        name="Barbershop_D1", 
        parent=None,
        simulation_time=simulation_time
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    sim.simulate_time(simulation_time)
    sim.exit()

    ### Output Final State
    final_state = {
        "time": simulation_time,
        "type": "state",
        "model": "Barbershop_D1",
        "field": "final_state",
        "value": "terminated"
    }
    print(json.dumps(final_state))
    ### END