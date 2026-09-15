### BEGIN: General Import
import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
### END

# The evaluator launches this runner with ``python -m package.runner``.
# The leading dot keeps the model import inside that generated package.
### BEGIN: Model import, must be relative
from .Offline_File_Transfer import Offline_File_Transfer
### END

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run Offline_File_Transfer simulation")
    
    # Define arguments based on Model Specification and Scenario
    # model_init_args: name, parent, simulation_time
    # CLI arg: --simulation_time
    parser.add_argument("--simulation_time", type=float, default=10000_000.0, help="Simulation duration in milliseconds (simulation time).")
    
    args = parser.parse_args()
    
    # Assign to local variables
    simulation_time = args.simulation_time
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    # Instantiate the model with required arguments
    model = Offline_File_Transfer(
        name="Offline_File_Transfer", 
        parent=None,
        simulation_time=simulation_time
    )
    
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    
    # Run simulation. Adding a tiny epsilon to ensure events exactly at the 
    # boundary time are processed (inclusive horizon).
    sim.simulate_time(simulation_time + 1e-9)
    
    sim.exit()
    ### END