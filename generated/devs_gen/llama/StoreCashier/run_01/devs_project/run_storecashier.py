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
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000", help="Simulation duration")
    parser.add_argument("--client_mean", type=float, default=10.0, help="Client inter-arrival mean")
    parser.add_argument("--client_stddev", type=float, default=5.0, help="Client inter-arrival stddev")
    parser.add_argument("--employee_1_mean", type=float, default=20.0, help="Employee 1 service mean")
    parser.add_argument("--employee_1_stddev", type=float, default=0.0, help="Employee 1 service stddev")
    parser.add_argument("--employee_2_mean", type=float, default=30.0, help="Employee 2 service mean")
    parser.add_argument("--employee_2_stddev", type=float, default=4.0, help="Employee 2 service stddev")
    parser.add_argument("--seed", type=int, default=None, help="Random seed")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity (optional, can use args.x directly)
    simulation_time = args.simulation_time
    client_mean = args.client_mean
    client_stddev = args.client_stddev
    employee_1_mean = args.employee_1_mean
    employee_1_stddev = args.employee_1_stddev
    employee_2_mean = args.employee_2_mean
    employee_2_stddev = args.employee_2_stddev
    seed = args.seed
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    model = StoreCashier( # instance the model
        name="StoreCashier", 
        parent=None,
        simulation_time=simulation_time,
    )
    model.client_generator.client_mean = client_mean
    model.client_generator.client_stddev = client_stddev
    model.employee_1.employee_mean = employee_1_mean
    model.employee_1.employee_stddev = employee_1_stddev
    model.employee_2.employee_mean = employee_2_mean
    model.employee_2.employee_stddev = employee_2_stddev
    if seed is not None:
        # Set seed for reproducibility
        model.seed = seed
    
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # This example treats the duration as an inclusive observation horizon.
    # xDEVS stops before an event exactly at the requested bound, so advance
    # by a tiny amount when the scenario requires the boundary event.
    hours, minutes, seconds, milliseconds = map(int, simulation_time.split(':'))
    simulate_time = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    sim.simulate_time(simulate_time)
    sim.exit()
    ### END