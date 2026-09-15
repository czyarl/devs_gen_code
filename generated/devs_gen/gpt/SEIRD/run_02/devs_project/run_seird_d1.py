import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with: python -m package.runner
# The leading dot keeps the model import inside that generated package.
from .SEIRD_D1 import SEIRD_D1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run SEIRD_D1 (discrete-time SEIRD) simulation")

    # Model init args (exactly as specified)
    parser.add_argument(
        "--test_name",
        type=str,
        default="default_test",
        help="Name of the test case being run (used for identification/logging only).",
    )
    parser.add_argument(
        "--mortality",
        type=float,
        default=10.0,
        help="Mortality rate as percentage (0-100). Default: 10.0",
    )
    parser.add_argument(
        "--infectivity_period",
        type=float,
        default=14.0,
        help="Average days a person stays infectious. Must be > 0. Default: 14.0",
    )
    parser.add_argument(
        "--dt",
        type=float,
        default=0.1,
        help="Time step for numerical integration in days. Must be > 0. Default: 0.1",
    )
    parser.add_argument(
        "--incubation_period",
        type=float,
        default=5.0,
        help="Average days from exposure to becoming infectious. Must be > 0. Default: 5.0",
    )
    parser.add_argument(
        "--total_population",
        type=int,
        default=1000,
        help="Total population size (integer >= 0). Default: 1000",
    )
    parser.add_argument(
        "--initial_infective",
        type=int,
        default=10,
        help="Initial number of infective individuals. Default: 10",
    )
    parser.add_argument(
        "--transmission_rate",
        type=float,
        default=2.5,
        help="Transmission rate (beta) per day. Default: 2.5",
    )
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=10.0,
        help="Total simulation time in days. Default: 10.0",
    )

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Runner stop horizon (scenario defines a fixed observation horizon)
    simulate_time = float(args.simulation_time)

    # --- Initialization (strict order) ---
    clock = SimulationClock()
    set_global_clock(clock)

    model = SEIRD_D1(
        name="SEIRD_D1",
        parent=None,
        test_name=args.test_name,
        mortality=float(args.mortality),
        infectivity_period=float(args.infectivity_period),
        dt=float(args.dt),
        incubation_period=float(args.incubation_period),
        total_population=int(args.total_population),
        initial_infective=int(args.initial_infective),
        transmission_rate=float(args.transmission_rate),
        simulation_time=float(args.simulation_time),
    )

    sim = Coordinator(model, clock)

    # --- Simulation Execution ---
    sim.initialize()
    # Inclusive horizon: allow events scheduled exactly at simulation_time to be processed if needed.
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()


if __name__ == "__main__":
    main()