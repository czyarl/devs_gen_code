### BEGIN: General Import
import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
### END

# The evaluator launches this runner with ``python -m package.runner``.
# The leading dot keeps the model import inside that generated package.
### BEGIN: Model import, must be relative
from .Barbershop_D1 import Barbershop_D1
### END

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run Barbershop_D1 simulation")
    
    # Define arguments with defaults suitable for the scenario
    # Based on System Registry and Scenario requirements
    parser.add_argument("--simulation_time", type=float, default=1000000.0, help="Total simulation time in seconds.")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity
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
    # This example treats the duration as an inclusive observation horizon.
    # xDEVS stops before an event exactly at the requested bound, so advance
    # by a tiny amount when the scenario requires the boundary event.
    sim.simulate_time(simulation_time + 1e-9)
    sim.exit()
    ### END