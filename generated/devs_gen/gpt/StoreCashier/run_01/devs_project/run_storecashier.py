import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with `python -m package.run`.
# The leading dot keeps the model import inside that generated package.
from .StoreCashier import StoreCashier


def parse_hhmmssmmm_to_seconds(value: str) -> float:
    """
    Parse a duration string in HH:MM:SS:mmm format into seconds (float).
    Example: "00:05:00:000" -> 300.0
    """
    parts = value.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid simulation_time '{value}'. Expected format HH:MM:SS:mmm")

    hh_s, mm_s, ss_s, mmm_s = parts
    hh = int(hh_s)
    mm = int(mm_s)
    ss = int(ss_s)
    mmm = int(mmm_s)

    if hh < 0 or mm < 0 or ss < 0 or mmm < 0:
        raise ValueError(f"Invalid simulation_time '{value}'. Negative values are not allowed")
    if mm >= 60 or ss >= 60 or mmm >= 1000:
        raise ValueError(f"Invalid simulation_time '{value}'. Expected MM,SS in [0,59] and mmm in [0,999]")

    return hh * 3600.0 + mm * 60.0 + ss + (mmm / 1000.0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run StoreCashier simulation")

    # Runner-only stop horizon (scenario-defined)
    parser.add_argument(
        "--simulation_time",
        type=str,
        default="00:05:00:000",
        help='Total simulation horizon in "HH:MM:SS:mmm" format (default: "00:05:00:000")',
    )

    # StoreCashier model init args (scenario defaults)
    parser.add_argument("--client_mean", type=float, default=10.0, help="Client inter-arrival mean (seconds)")
    parser.add_argument("--client_stddev", type=float, default=5.0, help="Client inter-arrival stddev (seconds)")
    parser.add_argument("--employee_1_mean", type=float, default=20.0, help="Employee 1 service-time mean (seconds)")
    parser.add_argument("--employee_1_stddev", type=float, default=0.0, help="Employee 1 service-time stddev (seconds)")
    parser.add_argument("--employee_2_mean", type=float, default=30.0, help="Employee 2 service-time mean (seconds)")
    parser.add_argument("--employee_2_stddev", type=float, default=4.0, help="Employee 2 service-time stddev (seconds)")
    parser.add_argument("--seed", type=int, default=None, help="Optional RNG seed for reproducibility")

    args = parser.parse_args()

    simulate_time = parse_hhmmssmmm_to_seconds(args.simulation_time)

    clock = SimulationClock()
    set_global_clock(clock)

    model = StoreCashier(
        name="StoreCashier",
        parent=None,
        client_mean=args.client_mean,
        client_stddev=args.client_stddev,
        employee_1_mean=args.employee_1_mean,
        employee_1_stddev=args.employee_1_stddev,
        employee_2_mean=args.employee_2_mean,
        employee_2_stddev=args.employee_2_stddev,
        seed=args.seed,
    )

    sim = Coordinator(model, clock)

    sim.initialize()
    # Treat as an inclusive observation horizon; allow events exactly at the boundary.
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()