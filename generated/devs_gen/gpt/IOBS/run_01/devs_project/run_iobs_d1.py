import argparse
import time
import random

from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with: python -m package.run
# The leading dot keeps the model import inside that generated package.
from .IOBS_D1 import IOBS_D1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run IOBS_D1 (Internet Online Banking System) DEVS simulation")

    # Runner-only stop horizon (scenario-specified)
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=1000000.0,
        help="Total simulation time in seconds (stop horizon).",
    )

    # Exact model init args from the registry/spec (scenario-derived defaults)
    parser.add_argument(
        "--processing_delay_s",
        type=float,
        default=10.0,
        help="Fixed processing delay (seconds) for AAM1/ANV1/PV1/BPM1/TPM1.",
    )
    parser.add_argument(
        "--initial_balance",
        type=int,
        default=3000,
        help="Initial account balance used by TPM1.",
    )
    parser.add_argument(
        "--bill_amount_min",
        type=int,
        default=0,
        help="Minimum bill amount BPM1 may generate (inclusive).",
    )
    parser.add_argument(
        "--bill_amount_max",
        type=int,
        default=40,
        help="Maximum bill amount BPM1 may generate (inclusive), before constraining by remaining balance.",
    )

    args = parser.parse_args()

    # Seed RNGs using system time (scenario requirement). Note: models may use random internally.
    random.seed(time.time_ns())

    simulation_time = args.simulation_time

    clock = SimulationClock()
    set_global_clock(clock)

    model = IOBS_D1(
        name="IOBS_D1",
        parent=None,
        processing_delay_s=args.processing_delay_s,
        initial_balance=args.initial_balance,
        bill_amount_min=args.bill_amount_min,
        bill_amount_max=args.bill_amount_max,
    )
    sim = Coordinator(model, clock)

    sim.initialize()
    # Treat simulation_time as an inclusive observation horizon.
    sim.simulate_time(simulation_time + 1e-9)
    sim.exit()


if __name__ == "__main__":
    main()