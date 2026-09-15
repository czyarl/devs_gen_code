import argparse
from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

from .StoreCashier import StoreCashier


def parse_hhmmssmmm(duration: str) -> float:
    """
    Parse a duration in 'HH:MM:SS:mmm' format into seconds (float).
    Example: '00:05:00:000' -> 300.0
    """
    parts = duration.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid duration '{duration}'. Expected format HH:MM:SS:mmm")
    hh, mm, ss, mmm = parts
    hours = int(hh)
    minutes = int(mm)
    seconds = int(ss)
    millis = int(mmm)
    if minutes < 0 or minutes >= 60 or seconds < 0 or seconds >= 60 or millis < 0 or millis >= 1000:
        raise ValueError(f"Invalid duration '{duration}'. Expected MM,SS in [0,59] and mmm in [0,999]")
    return hours * 3600.0 + minutes * 60.0 + seconds + millis / 1000.0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run StoreCashier simulation")

    # Runner-only horizon argument (scenario-specified name)
    parser.add_argument(
        "--simulation_time",
        type=str,
        default="00:05:00:000",
        help="Total simulation horizon in HH:MM:SS:mmm format (default: 00:05:00:000)",
    )

    # StoreCashier model init args (exactly as specified)
    parser.add_argument("--client_mean", type=float, default=10.0, help="Client inter-arrival mean in seconds")
    parser.add_argument("--client_stddev", type=float, default=5.0, help="Client inter-arrival stddev in seconds")
    parser.add_argument("--employee_1_mean", type=float, default=20.0, help="Employee 1 service mean in seconds")
    parser.add_argument("--employee_1_stddev", type=float, default=0.0, help="Employee 1 service stddev in seconds")
    parser.add_argument("--employee_2_mean", type=float, default=30.0, help="Employee 2 service mean in seconds")
    parser.add_argument("--employee_2_stddev", type=float, default=4.0, help="Employee 2 service stddev in seconds")
    parser.add_argument("--seed", type=int, default=None, help="Optional RNG seed for reproducibility")

    args = parser.parse_args()

    simulate_time = parse_hhmmssmmm(args.simulation_time)

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
    # Treat the provided duration as an inclusive observation horizon.
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()