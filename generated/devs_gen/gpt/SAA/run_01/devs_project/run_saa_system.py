import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with ``python -m package.run`` (as a module).
# The leading dot keeps the model import inside that generated package.
from .SAA_System import SAA_System


def main() -> None:
    parser = argparse.ArgumentParser(description="Run SAA_System simulation")

    # Model init args (exactly as declared by SAA_System)
    parser.add_argument(
        "--test_name",
        type=str,
        default="default_test",
        help="Identifier copied into the final output JSON.",
    )
    parser.add_argument(
        "--input_file",
        type=str,
        default="",
        help="Path to input request file. Empty means no requests.",
    )
    parser.add_argument(
        "--alarm_admin_delay",
        type=float,
        default=10.0,
        help="AlarmAdmin delay in seconds.",
    )
    parser.add_argument(
        "--authentication_delay",
        type=float,
        default=2.0,
        help="Authentication delay in seconds.",
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
        help="Maximum simulated time horizon in seconds.",
    )

    args = parser.parse_args()

    # Runner-only stop horizon: the scenario defines an explicit maximum simulated time.
    simulate_time = float(args.max_simulation_time)

    clock = SimulationClock()
    set_global_clock(clock)

    model = SAA_System(
        name="SAA_System",
        parent=None,
        test_name=args.test_name,
        input_file=(args.input_file if args.input_file else None),
        alarm_admin_delay=float(args.alarm_admin_delay),
        authentication_delay=float(args.authentication_delay),
        display_delay=float(args.display_delay),
        max_simulation_time=float(args.max_simulation_time),
    )

    sim = Coordinator(model, clock)

    sim.initialize()
    # Include events exactly at the horizon if any are scheduled there.
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()


if __name__ == "__main__":
    main()