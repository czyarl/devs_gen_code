import argparse
import sys
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .SAA_System import SAA_System

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run SAA_System simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--test_name", type=str, default="secure_area_access_test", help="Identifier copied into the final report")
    parser.add_argument("--input_file", type=str, default="input_requests.txt", help="Input request file path")
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0, help="Delay for alarm admin processing in seconds")
    parser.add_argument("--authentication_delay", type=float, default=2.0, help="Delay for authentication in seconds")
    parser.add_argument("--display_delay", type=float, default=3.0, help="Delay for display update in seconds")
    parser.add_argument("--max_simulation_time", type=float, default=1000.0, help="Maximum simulation time allowed")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity
    test_name = args.test_name
    input_file = args.input_file
    alarm_admin_delay = args.alarm_admin_delay
    authentication_delay = args.authentication_delay
    display_delay = args.display_delay
    max_simulation_time = args.max_simulation_time
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    model = SAA_System( # instance the model
        name="SAA_System", 
        parent=None,
        input_file=input_file,
        test_name=test_name,
        alarm_admin_delay=alarm_admin_delay,
        authentication_delay=authentication_delay,
        display_delay=display_delay,
        max_simulation_time=max_simulation_time
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # The scenario says to run until all accepted display events are produced
    # or max_simulation_time is reached. The model should handle this internally.
    sim.simulate_time(max_simulation_time)
    sim.exit()
    ### END