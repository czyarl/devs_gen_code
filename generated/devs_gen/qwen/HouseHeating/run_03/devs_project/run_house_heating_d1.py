import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .House_Heating_D1 import House_Heating_D1

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run House_Heating_D1 simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--simulate_time", type=float, default=60, help="Simulation duration in seconds")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity
    simulate_time = args.simulate_time
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    model = House_Heating_D1( # instance the model
        name="House_Heating_D1", 
        parent=None,
        simulate_time=simulate_time
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # This example treats the duration as an inclusive observation horizon.
    # xDEVS stops before an event exactly at the requested bound, so advance
    # by a tiny amount when the scenario requires the boundary event.
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()
    ### END