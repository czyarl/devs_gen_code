import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .StoreCashier import StoreCashier

if __name__ == "__main__":
    # 1. Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run StoreCashier simulation")

    # Simulation horizon argument (Runner-only, not passed to model)
    parser.add_argument(
        "--simulation_time",
        type=str,
        default="00:05:00:000",
        help="Total simulation horizon in HH:MM:SS:mmm format"
    )

    # Model initialization arguments based on System Registry and Scenario defaults
    parser.add_argument("--client_mean", type=float, default=10.0, help="Mean inter-arrival time in seconds")
    parser.add_argument("--client_stddev", type=float, default=5.0, help="Standard deviation of inter-arrival time in seconds")
    parser.add_argument("--employee_1_mean", type=float, default=20.0, help="Mean service duration for Employee 1 in seconds")
    parser.add_argument("--employee_1_stddev", type=float, default=0.0, help="Standard deviation of service duration for Employee 1 in seconds")
    parser.add_argument("--employee_2_mean", type=float, default=30.0, help="Mean service duration for Employee 2 in seconds")
    parser.add_argument("--employee_2_stddev", type=float, default=4.0, help="Standard deviation of service duration for Employee 2 in seconds")
    parser.add_argument("--seed", type=int, default=None, help="Optional seed for random number generation")

    args = parser.parse_args()

    # Parse the formatted simulation time string into numeric seconds
    # Format: HH:MM:SS:mmm
    time_parts = args.simulation_time.split(":")
    hours = int(time_parts[0])
    minutes = int(time_parts[1])
    seconds = int(time_parts[2])
    milliseconds = int(time_parts[3])
    
    simulate_time = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0

    # 2. Initialization
    clock = SimulationClock()
    set_global_clock(clock)

    # Instantiate the root model with the parsed arguments
    model = StoreCashier(
        name="StoreCashier",
        parent=None,
        client_mean=args.client_mean,
        client_stddev=args.client_stddev,
        employee_1_mean=args.employee_1_mean,
        employee_1_stddev=args.employee_1_stddev,
        employee_2_mean=args.employee_2_mean,
        employee_2_stddev=args.employee_2_stddev,
        seed=args.seed
    )

    sim = Coordinator(model, clock)

    # 3. Simulation Execution
    sim.initialize()
    
    # Run to the specified horizon. 
    # Adding a tiny epsilon ensures events exactly at the boundary are processed.
    sim.simulate_time(simulate_time + 1e-9)
    
    sim.exit()