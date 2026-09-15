import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

from .SAA_System import SAA_System

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run SAA_System simulation")
    
    # Define arguments based on model_init_args and scenario defaults
    parser.add_argument("--test_name", type=str, default="default_test", help="Test identifier provided via --test_name.")
    parser.add_argument("--input_file", type=str, default=None, help="Path to the input request file provided via --input_file.")
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0, help="Delay for AlarmAdmin stage. Default 10.0.")
    parser.add_argument("--authentication_delay", type=float, default=2.0, help="Delay for Authentication stage. Default 2.0.")
    parser.add_argument("--display_delay", type=float, default=3.0, help="Delay for Display stage. Default 3.0.")
    parser.add_argument("--max_simulation_time", type=float, default=1000.0, help="Maximum simulation horizon. Default 1000.0.")
    
    args = parser.parse_args()
    ### END

    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    model = SAA_System(
        name="SAA_System",
        parent=None,
        input_file=args.input_file,
        test_name=args.test_name,
        alarm_admin_delay=args.alarm_admin_delay,
        authentication_delay=args.authentication_delay,
        display_delay=args.display_delay,
        max_simulation_time=args.max_simulation_time
    )
    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()
    # Run until the max_simulation_time. Adding a small epsilon ensures events 
    # scheduled exactly at the boundary are processed if the logic allows.
    sim.simulate_time(args.max_simulation_time + 1e-9)
    sim.exit()
    ### END