### BEGIN: General Import
import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
### END

### BEGIN: Model import, must be relative
from .StoreCashier import StoreCashier
### END

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run StoreCashier simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--client_mean", type=float, default=10.0, help="Seconds between jobs; explicit scenario configuration")
    parser.add_argument("--client_stddev", type=float, default=5.0, help="Seconds between jobs; explicit scenario configuration")
    parser.add_argument("--employee_1_mean", type=float, default=20.0, help="Seconds per job; explicit scenario configuration")
    parser.add_argument("--employee_1_stddev", type=float, default=0.0, help="Seconds per job; explicit scenario configuration")
    parser.add_argument("--employee_2_mean", type=float, default=30.0, help="Seconds per job; explicit scenario configuration")
    parser.add_argument("--employee_2_stddev", type=float, default=4.0, help="Seconds per job; explicit scenario configuration")
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000", help="Total simulation horizon in HH:MM:SS:mmm format")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity (optional, can use args.x directly)
    client_mean = args.client_mean
    client_stddev = args.client_stddev
    employee_1_mean = args.employee_1_mean
    employee_1_stddev = args.employee_1_stddev
    employee_2_mean = args.employee_2_mean
    employee_2_stddev = args.employee_2_stddev
    simulation_time = args.simulation_time
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    # Parse simulation time from HH:MM:SS:mmm format
    hours, minutes, seconds, millis = simulation_time.split(":")
    simulate_time = int(hours)*3600 + int(minutes)*60 + int(seconds) + int(millis)/1000
    
    model = StoreCashier( # instance the model
        name="StoreCashier", 
        parent=None,
        client_mean=client_mean,
        client_stddev=client_stddev,
        employee_1_mean=employee_1_mean,
        employee_1_stddev=employee_1_stddev,
        employee_2_mean=employee_2_mean,
        employee_2_stddev=employee_2_stddev,
        simulation_time=simulation_time
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    sim.simulate_time(simulate_time)
    sim.exit()
    ### END