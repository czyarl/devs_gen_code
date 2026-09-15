import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with ``python -m package.runner``.
# The leading dot keeps the model import inside that generated package.
from .SEIRD_D1 import SEIRD_D1


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run SEIRD_D1 discrete-time SEIRD simulation")

    # Model init args (exactly as declared by SEIRD_D1.__init__)
    parser.add_argument(
        "--test_name",
        type=str,
        default="default_test",
        help="Required label for the run; used only for identification/logging by the model.",
    )
    parser.add_argument(
        "--mortality",
        type=float,
        default=10.0,
        help="Mortality percentage in [0,100] used in I->D and I->R split.",
    )
    parser.add_argument(
        "--infectivity_period",
        type=float,
        default=14.0,
        help="Positive days infectious; used in I->D and I->R rates.",
    )
    parser.add_argument(
        "--dt",
        type=float,
        default=0.1,
        help="Positive discrete update step in days.",
    )
    parser.add_argument(
        "--incubation_period",
        type=float,
        default=5.0,
        help="Positive days from exposed to infective; used in E->I rate.",
    )
    parser.add_argument(
        "--total_population",
        type=int,
        default=1000,
        help="Integer N >= 0, closed population size.",
    )
    parser.add_argument(
        "--initial_infective",
        type=int,
        default=10,
        help="Integer I0 with 0 <= I0 <= N.",
    )
    parser.add_argument(
        "--transmission_rate",
        type=float,
        default=2.5,
        help="Beta (β) per day used in S->E rate β*S*I/N.",
    )
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=10.0,
        help="Final reporting horizon in days; final report uses time=simulation_time.",
    )

    return parser


def main() -> None:
    parser = _build_arg_parser()
    args = parser.parse_args()

    # Runner-only stop horizon (also passed to model because SEIRD_D1 declares it)
    simulate_time = float(args.simulation_time)

    # 3. Initialization (strict order)
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

    # 4. Simulation Execution
    sim.initialize()
    # Scenario: updates occur at k*dt strictly less than simulation_time; final report uses time=simulation_time.
    # Run to the observation horizon; no epsilon is required by the scenario.
    sim.simulate_time(simulate_time)
    sim.exit()


if __name__ == "__main__":
    main()