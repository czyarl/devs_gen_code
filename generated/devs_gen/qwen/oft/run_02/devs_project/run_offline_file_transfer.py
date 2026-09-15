import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .Offline_File_Transfer import Offline_File_Transfer

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run Offline_File_Transfer simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--simulation_time", type=float, default=10000.0, help="Simulation duration in milliseconds")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity
    simulate_time = args.simulation_time
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    model = Offline_File_Transfer( # instance the model
        name="Offline_File_Transfer", 
        parent=None,
        simulation_time=simulate_time
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # Run simulation for the specified time
    sim.simulate_time(simulate_time)
    sim.exit()
    ### END