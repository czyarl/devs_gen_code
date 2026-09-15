import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .SEIRD_D1 import SEIRD_D1

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run SEIRD_D1 simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--test_name", type=str, default="seird_simulation", help="Name of the test case being run")
    parser.add_argument("--mortality", type=float, default=10.0, help="Mortality rate as percentage (0-100)")
    parser.add_argument("--infectivity_period", type=float, default=14.0, help="Average days a person stays infectious")
    parser.add_argument("--dt", type=float, default=0.1, help="Time step for numerical integration in days")
    parser.add_argument("--incubation_period", type=float, default=5.0, help="Average days from exposure to becoming infectious")
    parser.add_argument("--total_population", type=int, default=1000, help="Total population size")
    parser.add_argument("--initial_infective", type=int, default=10, help="Initial number of infected individuals")
    parser.add_argument("--transmission_rate", type=float, default=2.5, help="Transmission rate (β) per day")
    parser.add_argument("--simulation_time", type=float, default=10.0, help="Total simulation time in days")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity
    test_name = args.test_name
    mortality = args.mortality
    infectivity_period = args.infectivity_period
    dt = args.dt
    incubation_period = args.incubation_period
    total_population = args.total_population
    initial_infective = args.initial_infective
    transmission_rate = args.transmission_rate
    simulate_time = args.simulation_time
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    model = SEIRD_D1( # instance the model
        name="SEIRD_D1", 
        parent=None,
        mortality=mortality,
        infectivity_period=infectivity_period,
        dt=dt,
        incubation_period=incubation_period,
        total_population=total_population,
        initial_infective=initial_infective,
        transmission_rate=transmission_rate,
        simulation_time=simulate_time
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