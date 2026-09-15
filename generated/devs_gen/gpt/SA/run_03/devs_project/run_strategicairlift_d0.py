### BEGIN: General Import
import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock
### END

# The evaluator launches this runner with ``python -m package.run`` (as a module).
# The leading dot keeps the model import inside that generated package.
### BEGIN: Model import, must be relative
from .StrategicAirlift_D0 import StrategicAirlift_D0
### END


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run StrategicAirlift_D0 simulation")

    # Model init args (exactly as declared by StrategicAirlift_D0)
    parser.add_argument(
        "--duration",
        type=float,
        default=10000.0,
        help="Total simulation duration in seconds; Facility generates pallets while t < duration.",
    )
    parser.add_argument(
        "--num_aircraft",
        type=int,
        default=2,
        help="Number of aircraft instances (>= 1).",
    )
    parser.add_argument(
        "--pallet_interval",
        type=float,
        default=25.0,
        help="Inter-arrival time between generated pallets (seconds).",
    )
    parser.add_argument(
        "--pallet_expiration_time",
        type=float,
        default=150.0,
        help="Relative expiration window while pallet remains in LoadingQueue (seconds).",
    )
    parser.add_argument(
        "--flight_time",
        type=float,
        default=30.0,
        help="Flight-to-destination duration (seconds).",
    )
    parser.add_argument(
        "--unload_time",
        type=float,
        default=2.0,
        help="Unload duration at destination (seconds).",
    )
    parser.add_argument(
        "--return_time",
        type=float,
        default=30.0,
        help="Return-to-facility duration (seconds).",
    )
    parser.add_argument(
        "--maintenance_time",
        type=float,
        default=10.0,
        help="Maintenance duration after return (seconds).",
    )

    # Runner stop horizon:
    # Scenario defines a fixed observation horizon ("Simulation continues until total_duration time is reached.")
    # We therefore simulate to args.duration (with epsilon to include events at exactly duration if any).
    parser.add_argument(
        "--simulate_time",
        type=float,
        default=None,
        help="Optional runner stop horizon override (seconds). Defaults to --duration.",
    )

    return parser


def main(argv=None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    if args.num_aircraft < 1:
        raise ValueError("--num_aircraft must be >= 1")

    # Determine simulation stop horizon.
    # Use args.duration as the scenario horizon unless explicitly overridden.
    simulate_time = args.duration if args.simulate_time is None else args.simulate_time

    ### BEGIN: Initialization (strict order)
    clock = SimulationClock()
    set_global_clock(clock)

    model = StrategicAirlift_D0(
        name="StrategicAirlift_D0",
        parent=None,
        duration=float(args.duration),
        num_aircraft=int(args.num_aircraft),
        pallet_interval=float(args.pallet_interval),
        pallet_expiration_time=float(args.pallet_expiration_time),
        flight_time=float(args.flight_time),
        unload_time=float(args.unload_time),
        return_time=float(args.return_time),
        maintenance_time=float(args.maintenance_time),
    )

    sim = Coordinator(model, clock)
    ### END

    ### BEGIN: Simulation Execution
    sim.initialize()

    # Include boundary events if any atomic schedules exactly at simulate_time.
    sim.simulate_time(float(simulate_time) + 1e-9)

    sim.exit()
    ### END

    return 0


if __name__ == "__main__":
    raise SystemExit(main())