import argparse
import sys
import json
import logging
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with ``python -m package.run`` (or similar).
# The leading dot keeps the model import inside that generated package.
from .StrategicAirlift_D0 import StrategicAirlift_D0


def _positive_float(x: str) -> float:
    try:
        v = float(x)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e
    if v < 0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return v


def _positive_int_ge_1(x: str) -> int:
    try:
        v = int(x)
    except ValueError as e:
        raise argparse.ArgumentTypeError(str(e)) from e
    if v < 1:
        raise argparse.ArgumentTypeError("value must be >= 1")
    return v


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run StrategicAirlift_D0 simulation")

    # Model init args (exactly as declared by StrategicAirlift_D0)
    parser.add_argument("--duration", type=_positive_float, default=10000.0,
                        help="Total simulation time horizon used by Facility to stop generating pallets at t >= duration.")
    parser.add_argument("--num_aircraft", type=_positive_int_ge_1, default=2,
                        help="Number of Aircraft instances (>= 1).")
    parser.add_argument("--pallet_interval", type=_positive_float, default=25.0,
                        help="Facility inter-generation interval.")
    parser.add_argument("--pallet_expiration_time", type=_positive_float, default=150.0,
                        help="Relative expiration window while pallet remains in LoadingQueue.")
    parser.add_argument("--flight_time", type=_positive_float, default=30.0,
                        help="Aircraft flight-to-destination duration.")
    parser.add_argument("--unload_time", type=_positive_float, default=2.0,
                        help="Aircraft unload duration; delivery occurs at unload completion.")
    parser.add_argument("--return_time", type=_positive_float, default=30.0,
                        help="Aircraft return-to-facility duration.")
    parser.add_argument("--maintenance_time", type=_positive_float, default=10.0,
                        help="Aircraft maintenance/rest duration after return before becoming idle again.")

    args = parser.parse_args(argv)

    # stderr-only logging (runner must not write non-JSON to stdout)
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")
    log = logging.getLogger("run")

    # Stop condition:
    # Scenario defines a fixed observation horizon ("Simulation continues until total_duration time is reached").
    # Include any events scheduled exactly at t == duration with a tiny epsilon.
    simulate_time = float(args.duration) + 1e-9

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

    # Run
    try:
        sim.initialize()
        sim.simulate_time(simulate_time)
        sim.exit()
    except Exception as e:
        # Keep stdout clean; report errors to stderr.
        log.exception("Simulation failed: %s", e)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())