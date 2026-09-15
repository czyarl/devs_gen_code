### BEGIN: General Import
import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
### END

### BEGIN: Model import, must be relative
from .Offline_File_Transfer import Offline_File_Transfer
### END

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run Offline_File_Transfer simulation")
    
    # Argument defined in Simulation Scenario
    # The scenario specifies the argument is in milliseconds.
    parser.add_argument("--simulation_time", type=float, default=10000_000.0, help="Simulation duration in milliseconds (simulation time)")
    
    args = parser.parse_args()
    
    # Convert milliseconds to seconds for the simulation.
    # The scenario logic describes times in seconds (e.g., "10s preparing"), 
    # and the prompt instructions ("parse into seconds") imply the simulator uses seconds as the base unit.
    simulation_time_seconds = args.simulation_time / 1000.0
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    # Model instantiation based on System Registry and Model Specification
    # Init args: name (str), parent (object)
    model = Offline_File_Transfer(
        name="Offline_File_Transfer",
        parent=None
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # Add a tiny epsilon to ensure events exactly at the boundary time are processed.
    sim.simulate_time(simulation_time_seconds + 1e-9)
    sim.exit()
    ### END