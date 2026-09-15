import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with ``python -m package.run``.
# The leading dot keeps the model import inside that generated package.
from .StrategicAirlift_D0 import StrategicAirlift_D0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run StrategicAirlift_D0 simulation")

    # Model init args (exactly as declared by StrategicAirlift_D0.__init__)
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
        help="Number of Aircraft instances (>= 1).",
    )
    parser.add_argument(
        "--pallet_interval",
        type=float,
        default=25.0,
        help="Seconds between pallet generations.",
    )
    parser.add_argument(
        "--pallet_expiration_time",
        type=float,
        default=150.0,
        help="Seconds after generation when a pallet expires while still in LoadingQueue.",
    )
    parser.add_argument(
        "--flight_time",
        type=float,
        default=30.0,
        help="Seconds for Aircraft to fly facility->destination.",
    )
    parser.add_argument(
        "--unload_time",
        type=float,
        default=2.0,
        help="Seconds for Aircraft to unload at destination; delivery occurs at unload completion.",
    )
    parser.add_argument(
        "--return_time",
        type=float,
        default=30.0,
        help="Seconds for Aircraft to fly destination->facility.",
    )
    parser.add_argument(
        "--maintenance_time",
        type=float,
        default=10.0,
        help="Seconds for Aircraft maintenance/rest before becoming idle again.",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Basic validation (keep minimal; do not add new parameters)
    if args.num_aircraft < 1:
        raise SystemExit("--num_aircraft must be >= 1")
    if args.duration < 0:
        raise SystemExit("--duration must be >= 0")
    for name in (
        "pallet_interval",
        "pallet_expiration_time",
        "flight_time",
        "unload_time",
        "return_time",
        "maintenance_time",
    ):
        if getattr(args, name) < 0:
            raise SystemExit(f"--{name} must be >= 0")

    # Runner stop horizon:
    # Scenario defines a fixed total simulation time horizon ("Simulation continues until total_duration time is reached").
    # Facility also uses `duration` to stop generating at t >= duration.
    simulate_time = float(args.duration)

    # Initialization (strict order)
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

    # Simulation execution
    sim.initialize()
    sim.simulate_time(simulate_time)
    sim.exit()


if __name__ == "__main__":
    main()