import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .StoreCashier import StoreCashier

def hmsmmm_to_seconds(hmsmmm_str):
    """Convert HH:MM:SS:mmm format to seconds as float."""
    h, m, s, ms = map(int, hmsmmm_str.split(':'))
    return h * 3600 + m * 60 + s + ms / 1000.0

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run StoreCashier simulation")
    
    # Define arguments matching the model's init args and scenario defaults
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000", help="Total simulation horizon in HH:MM:SS:mmm format")
    parser.add_argument("--client_mean", type=float, default=10.0, help="Mean inter-arrival time in seconds")
    parser.add_argument("--client_stddev", type=float, default=5.0, help="Standard deviation of inter-arrival time in seconds")
    parser.add_argument("--employee_1_mean", type=float, default=20.0, help="Mean service time for Employee1 in seconds")
    parser.add_argument("--employee_1_stddev", type=float, default=0.0, help="Standard deviation of service time for Employee1 in seconds")
    parser.add_argument("--employee_2_mean", type=float, default=30.0, help="Mean service time for Employee2 in seconds")
    parser.add_argument("--employee_2_stddev", type=float, default=4.0, help="Standard deviation of service time for Employee2 in seconds")

    args = parser.parse_args()

    # Convert simulation_time to numeric seconds
    simulate_time = hmsmmm_to_seconds(args.simulation_time)

    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock

    model = StoreCashier( # instance the model
        name="StoreCashier",
        parent=None,
        simulation_time=args.simulation_time,
        client_mean=args.client_mean,
        client_stddev=args.client_stddev,
        employee_1_mean=args.employee_1_mean,
        employee_1_stddev=args.employee_1_stddev,
        employee_2_mean=args.employee_2_mean,
        employee_2_stddev=args.employee_2_stddev
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # Simulation time is inclusive; xDEVS stops before the exact time,
    # so we add a small epsilon to ensure boundary events are included.
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()
    ### END