### BEGIN: General Import
import argparse
import json
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock, get_current_time
### END

### BEGIN: Model import, must be relative
from .SAA_System import SAA_System
### END

def main():
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run SAA_System simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--test_name", type=str, default="SAA_System_test", help="Identifier copied into the final report")
    parser.add_argument("--input_file", type=str, default=None, help="Input request file path")
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0, help="Alarm admin delay (seconds)")
    parser.add_argument("--authentication_delay", type=float, default=2.0, help="Authentication delay (seconds)")
    parser.add_argument("--display_delay", type=float, default=3.0, help="Display delay (seconds)")
    parser.add_argument("--max_simulation_time", type=float, default=1000.0, help="Maximum simulation time (seconds)")
    
    args = parser.parse_args()
    
    # Assign to local variables for clarity (optional, can use args.x directly)
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
    sim.simulate_time(max_simulation_time)
    sim.exit()
    
    output = model.output
    print(json.dumps({
        "test_name": test_name,
        "simulation_time": get_current_time(),
        "initial_state": model.initial_state,
        "final_state": model.final_state,
        "events": model.events,
        "operations": model.operations
    }))
    ### END

if __name__ == "__main__":
    main()