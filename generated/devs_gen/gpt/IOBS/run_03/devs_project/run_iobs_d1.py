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

    # Runner-only stop horizon (per scenario)
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=1000000.0,
        help="Total simulation time horizon in seconds",
    )

    # Model init args (exactly as declared by IOBS_D1)
    parser.add_argument(
        "--stage_delay_s",
        type=float,
        default=10.0,
        help="Processing delay (seconds) for each processing stage (AAM1, ANV1, PV1, BPM1, TPM1)",
    )
    parser.add_argument(
        "--tpm_initial_balance",
        type=int,
        default=3000,
        help="Initial account balance for TPM1",
    )
    parser.add_argument(
        "--bpm_bill_min",
        type=int,
        default=0,
        help="Minimum bill amount BPM1 may generate (inclusive)",
    )
    parser.add_argument(
        "--bpm_bill_max",
        type=int,
        default=40,
        help="Maximum bill amount BPM1 may generate (inclusive), before constraining by remaining balance",
    )
    parser.add_argument(
        "--anv_pass_probability",
        type=float,
        default=0.5,
        help="Probability ANV1 passes verification",
    )
    parser.add_argument(
        "--pv_success_probability",
        type=float,
        default=0.5,
        help="Per-attempt probability PV1 succeeds password verification (PV retries internally until success)",
    )

    args = parser.parse_args()

    # Seed RNGs using system time (scenario requirement)
    random.seed(time.time_ns())

    simulation_time = float(args.simulation_time)

    clock = SimulationClock()
    set_global_clock(clock)

    model = IOBS_D1(
        name="IOBS_D1",
        parent=None,
        stage_delay_s=float(args.stage_delay_s),
        tpm_initial_balance=int(args.tpm_initial_balance),
        bpm_bill_min=int(args.bpm_bill_min),
        bpm_bill_max=int(args.bpm_bill_max),
        anv_pass_probability=float(args.anv_pass_probability),
        pv_success_probability=float(args.pv_success_probability),
    )

    sim = Coordinator(model, clock)

    sim.initialize()
    # Treat as an inclusive observation horizon; include events exactly at the boundary if any.
    sim.simulate_time(simulation_time + 1e-9)
    sim.exit()


if __name__ == "__main__":
    main()