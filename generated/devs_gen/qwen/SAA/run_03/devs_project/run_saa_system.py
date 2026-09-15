import argparse
import sys
import json
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# Import the target model using relative import as required
from .SAA_System import SAA_System

def main():
    parser = argparse.ArgumentParser(description="Run SAA_System simulation")
    
    # Define arguments matching the model's init args exactly
    parser.add_argument("--test_name", type=str, default="default_test", help="Identifier copied into the final report")
    parser.add_argument("--input_file", type=str, default=None, help="Input file path")
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0, help="Scenario constant")
    parser.add_argument("--authentication_delay", type=float, default=2.0, help="Scenario constant")
    parser.add_argument("--display_delay", type=float, default=3.0, help="Scenario constant")
    parser.add_argument("--max_simulation_time", type=float, default=1000.0, help="Scenario constant")
    
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
        input_path=input_file,
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
    # According to the scenario, we should run until max_simulation_time
    # or until all events are processed, whichever comes first.
    # The model itself should handle draining logic.
    sim.simulate_time(max_simulation_time)
    sim.exit()
    ### END

if __name__ == "__main__":
    main()