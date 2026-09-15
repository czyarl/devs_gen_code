### BEGIN: General Import
import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
### END

# The evaluator launches this runner with ``python -m package.run`` (or similar).
# The leading dot keeps the model import inside that generated package.
### BEGIN: Model import, must be relative
from .SAA_System import SAA_System
### END


def main() -> None:
    ### BEGIN: Parameter Configuration (ArgParse)
    parser = argparse.ArgumentParser(description="Run SAA_System simulation")

    # Model init args (exactly as declared by SAA_System)
    parser.add_argument(
        "--test_name",
        type=str,
        default="default_test",
        help="Copied into the output JSON field 'test_name'.",
    )
    parser.add_argument(
        "--input_file",
        type=str,
        default=None,
        help="Path to the request text file. If omitted, the source behaves as having zero requests.",
    )
    parser.add_argument(
        "--alarm_admin_delay",
        type=float,
        default=10.0,
        help="AlarmAdmin processing delay in seconds.",
    )
    parser.add_argument(
        "--authentication_delay",
        type=float,
        default=2.0,
        help="Authentication processing delay in seconds.",
    )
    parser.add_argument(
        "--display_delay",
        type=float,
        default=3.0,
        help="Display delay in seconds.",
    )
    parser.add_argument(
        "--max_simulation_time",
        type=float,
        default=1000.0,
        help="Maximum simulation time horizon in seconds.",
    )

    args = parser.parse_args()

    test_name = args.test_name
    input_file = args.input_file
    alarm_admin_delay = args.alarm_admin_delay
    authentication_delay = args.authentication_delay
    display_delay = args.display_delay
    max_simulation_time = args.max_simulation_time

    # Runner stop horizon: scenario defines a max time cap.
    simulate_time = max_simulation_time
    ### END: Parameter Configuration (ArgParse)

    ### BEGIN: Initialization
    clock = SimulationClock()
    set_global_clock(clock)

    model = SAA_System(
        name="SAA_System",
        parent=None,
        test_name=test_name,
        input_file=input_file,
        alarm_admin_delay=alarm_admin_delay,
        authentication_delay=authentication_delay,
        display_delay=display_delay,
        max_simulation_time=max_simulation_time,
    )

    sim = Coordinator(model, clock)
    ### END: Initialization

    ### BEGIN: Simulation Execution
    sim.initialize()
    # Treat max_simulation_time as an inclusive observation horizon.
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()
    ### END: Simulation Execution


if __name__ == "__main__":
    main()