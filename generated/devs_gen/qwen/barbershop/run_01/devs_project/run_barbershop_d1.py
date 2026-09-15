import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .Barbershop_D1 import Barbershop_D1

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run Barbershop_D1 simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--simulation_time", type=float, default=1000000.0, help="Total simulation time in seconds")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity
    simulate_time = args.simulation_time
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    model = Barbershop_D1( # instance the model
        name="Barbershop_D1", 
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