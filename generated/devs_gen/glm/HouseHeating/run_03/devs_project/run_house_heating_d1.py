import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with ``python -m package.runner``.
# The leading dot keeps the model import inside that generated package.
from .House_Heating_D1 import House_Heating_D1

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run House_Heating_D1 simulation")
    
    # Define arguments based on Model Specification and Scenario requirements
    # Model init args: name, parent, simulate_time
    # Scenario CLI arg: --simulate_time
    parser.add_argument(
        "--simulate_time", 
        type=float, 
        default=10.0, 
        help="Total simulation duration in seconds"
    )
    
    args = parser.parse_args()
    
    # Extract argument for clarity
    simulate_time = args.simulate_time
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    # Instantiate the model with the required arguments
    model = House_Heating_D1(
        name="House_Heating_D1",
        parent=None,
        simulate_time=simulate_time
    )
    
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    
    # The scenario requires observations for seconds 1 through int(simulate_time).
    # We add a tiny epsilon to ensure the event at the final boundary time is processed.
    sim.simulate_time(simulate_time + 1e-9)
    
    sim.exit()
    ### END