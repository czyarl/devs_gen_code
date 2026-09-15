### BEGIN: General Import
import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
### END

# The evaluator launches this runner with ``python -m package.runner``.
# The leading dot keeps the model import inside that generated package.
### BEGIN: Model import, must be relative
from .SAA_System import SAA_System
### END

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run SAA_System simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--test_name", type=str, default="SAA_Default_Test", help="Test identifier passed to ReportCollector")
    parser.add_argument("--input_file", type=str, default="", help="Path to the input file containing operation requests")
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0, help="Scenario constant passed to AlarmAdmin")
    parser.add_argument("--authentication_delay", type=float, default=2.0, help="Scenario constant passed to Authentication")
    parser.add_argument("--display_delay", type=float, default=3.0, help="Scenario constant passed to Display")
    parser.add_argument("--max_simulation_time", type=float, default=1000.0, help="Scenario constant passed to ReportCollector to determine simulation horizon")
    
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
    
    model = SAA_System(
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
    # Run up to max_simulation_time. Adding a tiny epsilon to ensure boundary events are captured.
    sim.simulate_time(max_simulation_time + 1e-9)
    sim.exit()
    ### END