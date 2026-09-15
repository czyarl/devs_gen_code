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
    
    # Arguments matching model_init_args
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000", 
                        help="Simulation horizon in HH:MM:SS:mmm format")
    parser.add_argument("--client_mean", type=float, default=10.0, 
                        help="Mean inter-arrival time")
    parser.add_argument("--client_stddev", type=float, default=5.0, 
                        help="Standard deviation of inter-arrival time")
    parser.add_argument("--employee_1_mean", type=float, default=20.0, 
                        help="Mean service duration for Employee 1")
    parser.add_argument("--employee_1_stddev", type=float, default=0.0, 
                        help="Standard deviation of service duration for Employee 1")
    parser.add_argument("--employee_2_mean", type=float, default=30.0, 
                        help="Mean service duration for Employee 2")
    parser.add_argument("--employee_2_stddev", type=float, default=4.0, 
                        help="Standard deviation of service duration for Employee 2")
    parser.add_argument("--seed", type=int, default=None, 
                        help="Random seed for reproducibility")
    
    args = parser.parse_args()
    
    # Parse the simulation time string to a numeric value for the Coordinator
    # Format: HH:MM:SS:mmm
    time_parts = args.simulation_time.split(':')
    hh = int(time_parts[0])
    mm = int(time_parts[1])
    ss = int(time_parts[2])
    mmm = int(time_parts[3])
    numeric_sim_time = hh * 3600 + mm * 60 + ss + mmm / 1000.0
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    # Instantiate the model. Note: simulation_time is passed as a string to the model
    # as per the model specification, while numeric_sim_time is used for the Coordinator.
    model = StoreCashier(
        name="StoreCashier",
        parent=None,
        simulation_time=args.simulation_time,
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
    
    # Simulate up to the horizon. 
    # Adding a tiny epsilon to ensure events exactly at the horizon are processed.
    sim.simulate_time(numeric_sim_time + 1e-9)
    
    sim.exit()
    ### END