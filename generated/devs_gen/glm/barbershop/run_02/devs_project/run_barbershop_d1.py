import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with ``python -m package.runner``.
# The leading dot keeps the model import inside that generated package.
from .Barbershop_D1 import Barbershop_D1

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run Barbershop_D1 simulation")
    
    # Define arguments for model initialization based on Model Specification
    parser.add_argument("--name", type=str, default="Barbershop_D1", help="Model instance name")
    
    # Define arguments for simulation control based on Simulation Scenario
    parser.add_argument("--simulation_time", type=float, default=1000000.0, help="Total simulation time in seconds")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity
    model_name = args.name
    simulation_time = args.simulation_time
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    # Instantiate the model
    # parent is None for the root model
    model = Barbershop_D1(
        name=model_name, 
        parent=None
    )
    
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    
    # The scenario specifies a default simulation time of 1000000.0 to ensure all requests are processed.
    # We add a tiny epsilon to ensure events exactly at the boundary are processed if necessary,
    # consistent with the reference code pattern.
    sim.simulate_time(simulation_time + 1e-9)
    
    sim.exit()
    ### END