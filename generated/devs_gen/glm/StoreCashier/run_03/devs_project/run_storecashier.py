### BEGIN: General Import
import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
### END

# The evaluator launches this runner with ``python -m package.runner``.
# The leading dot keeps the model import inside that generated package.
### BEGIN: Model import, must be relative
from .StoreCashier import StoreCashier
### END

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run StoreCashier simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000", help="Total simulation horizon in HH:MM:SS:mmm format")
    
    # Model initialization parameters
    parser.add_argument("--client_mean", type=float, default=10.0, help="Mean inter-arrival time for clients")
    parser.add_argument("--client_stddev", type=float, default=5.0, help="Standard deviation for client inter-arrival time")
    parser.add_argument("--employee_1_mean", type=float, default=20.0, help="Mean service duration for Employee 1")
    parser.add_argument("--employee_1_stddev", type=float, default=0.0, help="Standard deviation for Employee 1 service duration")
    parser.add_argument("--employee_2_mean", type=float, default=30.0, help="Mean service duration for Employee 2")
    parser.add_argument("--employee_2_stddev", type=float, default=4.0, help="Standard deviation for Employee 2 service duration")
    parser.add_argument("--seed", type=int, default=None, help="Optional random seed for reproducibility")
    
    args = parser.parse_args()
    
    # Parse simulation time string (HH:MM:SS:mmm) to float seconds
    time_parts = args.simulation_time.split(':')
    hours = int(time_parts[0])
    minutes = int(time_parts[1])
    seconds = int(time_parts[2])
    millis = int(time_parts[3])
    simulate_time = hours * 3600 + minutes * 60 + seconds + millis / 1000.0
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    model = StoreCashier( # instance the model
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
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # Add a tiny epsilon to ensure events exactly at the horizon are processed
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()
    ### END