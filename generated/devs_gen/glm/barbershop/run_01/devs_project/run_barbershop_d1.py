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
    # The scenario specifies --simulation_time with a default of 1000000.0
    parser.add_argument("--simulation_time", type=float, default=1000000.0, help="Total simulation time in seconds")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity
    simulation_time = args.simulation_time
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    # Instantiate the model
    # Model specification requires 'name' and 'parent'.
    # We use the class name as the instance name and None for the root parent.
    model = Barbershop_D1(
        name="Barbershop_D1", 
        parent=None
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # The scenario defines a fixed observation horizon (simulation_time).
    # xDEVS stops before an event exactly at the requested bound, so advance
    # by a tiny amount to ensure events exactly at the boundary are processed.
    sim.simulate_time(simulation_time + 1e-9)
    sim.exit()
    ### END