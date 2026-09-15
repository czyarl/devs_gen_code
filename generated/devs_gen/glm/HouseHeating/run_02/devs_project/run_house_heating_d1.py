import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .House_Heating_D1 import House_Heating_D1

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run House_Heating_D1 simulation")
    
    # Define arguments based on scenario and model specification
    parser.add_argument("--simulate_time", type=float, default=60.0, help="Total simulation duration in seconds")
    
    args = parser.parse_args()
    
    # Extract arguments
    simulate_time = args.simulate_time
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    # Instantiate the model with arguments defined in the System Registry and required by validation
    model = House_Heating_D1(
        name="House_Heating_D1",
        parent=None,
        simulate_time=simulate_time
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # The scenario requires observations for seconds 1..int(simulate_time).
    # xDEVS stops before an event exactly at the requested bound, so we advance
    # by a tiny amount to ensure the boundary event is processed.
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()
    ### END