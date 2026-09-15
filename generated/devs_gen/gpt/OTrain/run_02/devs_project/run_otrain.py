import argparse
import time
import random

from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with ``python -m package.run``.
# The leading dot keeps the model import inside that generated package.
from .OTrain import OTrain


def parse_hhmmssmmm_to_seconds(value: str) -> float:
    """
    Parse duration formatted as "HH:MM:SS:mmm" into seconds (float).
    """
    parts = value.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"simulate_time must be in 'HH:MM:SS:mmm' format, got: {value!r}")
    hh, mm, ss, mmm = parts
    h = int(hh)
    m = int(mm)
    s = int(ss)
    ms = int(mmm)
    if h < 0 or m < 0 or s < 0 or ms < 0:
        raise ValueError(f"simulate_time must be non-negative, got: {value!r}")
    if m >= 60 or s >= 60 or ms >= 1000:
        raise ValueError(f"simulate_time fields out of range, got: {value!r}")
    return h * 3600.0 + m * 60.0 + s + ms / 1000.0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run OTrain simulation")

    # Runner-only horizon (scenario-defined CLI)
    parser.add_argument(
        "--simulate_time",
        type=str,
        default="00:01:00:000",
        help='Simulation duration in "HH:MM:SS:mmm" (default: 00:01:00:000)',
    )

    # OTrain model init args (exactly as specified)
    parser.add_argument("--name", type=str, default="OTrain", help="Model instance name")
    parser.add_argument(
        "--station_ids",
        type=str,
        default="[1, 2, 3, 4, 5]",
        help="Fixed station IDs in service order as JSON list (default: [1,2,3,4,5])",
    )
    parser.add_argument(
        "--station_names",
        type=str,
        default='{"1":"Bayview","2":"Carling","3":"Carleton","4":"Confed","5":"Greenboro"}',
        help='Mapping station_id->station_name as JSON object (default: {"1":"Bayview",...})',
    )
    parser.add_argument("--travel_interval_s", type=int, default=225, help="Travel time between stations (seconds)")
    parser.add_argument("--initial_train_station_id", type=int, default=1, help="Initial train station_id at t=0")
    parser.add_argument("--initial_train_direction", type=int, default=0, help="Initial train direction at t=0 (0/1)")
    parser.add_argument(
        "--route_sequence",
        type=str,
        default='[{"station_id":1,"direction":0},{"station_id":2,"direction":0},{"station_id":3,"direction":0},{"station_id":4,"direction":0},{"station_id":5,"direction":1},{"station_id":4,"direction":1},{"station_id":3,"direction":1},{"station_id":2,"direction":1},{"station_id":1,"direction":0}]',
        help="Repeating route as JSON list of {station_id,direction}",
    )
    parser.add_argument("--init_passenger_time_s", type=float, default=0.5, help="Init passenger creation time (seconds)")
    parser.add_argument("--gen_mean_min", type=float, default=5.0, help="Passenger interarrival mean (minutes)")
    parser.add_argument("--gen_std_min", type=float, default=5.0, help="Passenger interarrival std dev (minutes)")
    parser.add_argument("--gen_clamp_min_min", type=int, default=1, help="Lower clamp bound (minutes)")
    parser.add_argument("--gen_clamp_max_min", type=int, default=9, help="Upper clamp bound (minutes)")
    parser.add_argument("--board_alight_dt_s", type=float, default=0.025, help="Serial boarding/alighting step (seconds)")

    args = parser.parse_args()

    # Seed randomness from system time (runner-level; models may also seed internally)
    seed_ns = time.time_ns()
    random.seed(seed_ns)

    simulate_time = parse_hhmmssmmm_to_seconds(args.simulate_time)

    # Parse JSON-encoded structured args
    import json  # standard library; imported here to keep runner imports minimal/orderly

    station_ids = json.loads(args.station_ids)
    station_names_raw = json.loads(args.station_names)
    # Ensure keys are ints (JSON object keys are strings)
    station_names = {int(k): v for k, v in station_names_raw.items()}
    route_sequence = json.loads(args.route_sequence)

    # 3. Initialization (strict order)
    clock = SimulationClock()
    set_global_clock(clock)

    model = OTrain(
        name=args.name,
        parent=None,
        station_ids=station_ids,
        station_names=station_names,
        travel_interval_s=args.travel_interval_s,
        initial_train_station_id=args.initial_train_station_id,
        initial_train_direction=args.initial_train_direction,
        route_sequence=route_sequence,
        init_passenger_time_s=args.init_passenger_time_s,
        gen_mean_min=args.gen_mean_min,
        gen_std_min=args.gen_std_min,
        gen_clamp_min_min=args.gen_clamp_min_min,
        gen_clamp_max_min=args.gen_clamp_max_min,
        board_alight_dt_s=args.board_alight_dt_s,
    )

    sim = Coordinator(model, clock)

    # 4. Simulation execution
    sim.initialize()
    # Treat CLI duration as an inclusive observation horizon; include boundary events.
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()