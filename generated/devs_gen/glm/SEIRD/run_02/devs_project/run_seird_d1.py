import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .SEIRD_D1 import SEIRD_D1

if __name__ == "__main__":
    # Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run SEIRD_D1 simulation")

    # Define arguments based on model_init_args and scenario requirements
    parser.add_argument("--test_name", type=str, default="test_run", help="Name of the test case being run.")
    parser.add_argument("--dt", type=float, default=0.1, help="Time step for numerical integration in days.")
    parser.add_argument("--simulation_time", type=float, default=10.0, help="Total simulation time in days.")
    parser.add_argument("--total_population", type=int, default=1000, help="Total population size.")
    parser.add_argument("--initial_infective", type=int, default=10, help="Initial number of infected individuals.")
    parser.add_argument("--transmission_rate", type=float, default=2.5, help="Transmission rate (β) per day.")
    parser.add_argument("--incubation_period", type=float, default=5.0, help="Average days from exposure to becoming infectious.")
    parser.add_argument("--infectivity_period", type=float, default=14.0, help="Average days a person stays infectious.")
    parser.add_argument("--mortality", type=float, default=10.0, help="Mortality rate as percentage (0-100).")

    args = parser.parse_args()

    # Initialization
    clock = SimulationClock()
    set_global_clock(clock)

    # Instantiate the model
    # Note: test_name is not passed to the model as it is not in model_init_args
    model = SEIRD_D1(
        name="SEIRD_D1",
        parent=None,
        dt=args.dt,
        simulation_time=args.simulation_time,
        total_population=args.total_population,
        initial_infective=args.initial_infective,
        transmission_rate=args.transmission_rate,
        incubation_period=args.incubation_period,
        infectivity_period=args.infectivity_period,
        mortality=args.mortality
    )

    sim = Coordinator(model, clock)

    # Simulation Execution
    sim.initialize()
    
    # Scenario requires output at time = simulation_time.
    # xDEVS processes events with time < t, so we add a small epsilon to include the boundary event.
    sim.simulate_time(args.simulation_time + 1e-9)
    
    sim.exit()