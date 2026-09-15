import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
from .SAA_System import SAA_System

if __name__ == "__main__":
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run SAA_System simulation")
    
    # Define arguments with defaults suitable for the scenario
    parser.add_argument("--test_name", type=str, default="smoke_test", help="Identifier copied into the final report")
    parser.add_argument("--input_file", type=str, default="input.txt", help="Request file supplied by the runner")
    parser.add_argument("--alarm_admin_delay", type=float, default=10.0, help="Explicit scenario constant")
    parser.add_argument("--authentication_delay", type=float, default=2.0, help="Explicit scenario constant")
    parser.add_argument("--display_delay", type=float, default=3.0, help="Explicit scenario constant")
    parser.add_argument("--max_simulation_time", type=float, default=1000.0, help="Explicit scenario constant")
    
    args = parser.parse_args()
    
    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock) # register the clock
    
    model = SAA_System(
        name="SAA_System",
        parent=None,
        input_path=args.input_file,
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
    # Run to the max_simulation_time horizon.
    # Adding a tiny epsilon to ensure events exactly at the boundary are processed.
    sim.simulate_time(args.max_simulation_time + 1e-9)
    sim.exit()
    ### END