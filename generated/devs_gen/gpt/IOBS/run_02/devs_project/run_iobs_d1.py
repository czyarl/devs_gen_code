import argparse
import time
import random

from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with ``python -m package.run`` (or similar).
# The leading dot keeps the model import inside that generated package.
from .IOBS_D1 import IOBS_D1


def main() -> None:
    parser = argparse.ArgumentParser(description="Run IOBS_D1 (Internet Online Banking System) DEVS simulation")

    # Runner stop horizon (scenario-defined)
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=1000000.0,
        help="Total simulation time horizon in seconds."
    )

    # Model init args (exactly as declared by IOBS_D1)
    parser.add_argument(
        "--processing_delay_s",
        type=float,
        default=10.0,
        help="Processing delay (seconds) applied by each processing entity (AAM1, ANV1, PV1, BPM1, TPM1)."
    )
    parser.add_argument(
        "--tpm_initial_balance",
        type=int,
        default=3000,
        help="Initial account balance for TPM1."
    )
    parser.add_argument(
        "--bpm_bill_amount_min",
        type=int,
        default=0,
        help="Minimum bill amount BPM1 may generate."
    )
    parser.add_argument(
        "--bpm_bill_amount_max",
        type=int,
        default=40,
        help="Maximum bill amount BPM1 may generate."
    )

    args = parser.parse_args()

    # Seed RNG from system time (scenario requirement)
    random.seed(time.time_ns())

    simulation_time = float(args.simulation_time)

    clock = SimulationClock()
    set_global_clock(clock)

    model = IOBS_D1(
        name="IOBS_D1",
        parent=None,
        processing_delay_s=float(args.processing_delay_s),
        tpm_initial_balance=int(args.tpm_initial_balance),
        bpm_bill_amount_min=int(args.bpm_bill_amount_min),
        bpm_bill_amount_max=int(args.bpm_bill_amount_max),
    )

    sim = Coordinator(model, clock)

    sim.initialize()
    # Treat as an inclusive observation horizon; include boundary events if any.
    sim.simulate_time(simulation_time + 1e-9)
    sim.exit()


if __name__ == "__main__":
    main()