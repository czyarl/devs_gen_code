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
    Parse duration formatted as 'HH:MM:SS:mmm' into seconds (float with milliseconds).
    Example: '00:01:00:000' -> 60.0
    """
    parts = value.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid duration '{value}'. Expected format 'HH:MM:SS:mmm'.")
    hh, mm, ss, mmm = parts
    h = int(hh)
    m = int(mm)
    s = int(ss)
    ms = int(mmm)
    if h < 0 or m < 0 or s < 0 or ms < 0:
        raise ValueError(f"Invalid duration '{value}'. Negative values are not allowed.")
    if m >= 60 or s >= 60 or ms >= 1000:
        raise ValueError(f"Invalid duration '{value}'. Expected MM<60, SS<60, mmm<1000.")
    return h * 3600.0 + m * 60.0 + s + (ms / 1000.0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run OTrain simulation")

    # Runner-only stop horizon (scenario-specified)
    parser.add_argument(
        "--simulate_time",
        type=str,
        default="00:01:00:000",
        help="Simulation duration in 'HH:MM:SS:mmm' (default: 00:01:00:000).",
    )

    # OTrain model init args (exactly as specified), with scenario-derived defaults
    parser.add_argument("--name", type=str, default="OTrain", help="Model instance name.")
    parser.add_argument(
        "--station_ids",
        type=int,
        nargs="+",
        default=[1, 2, 3, 4, 5],
        help="Fixed station ID list (default: 1 2 3 4 5).",
    )
    parser.add_argument(
        "--station_names",
        type=str,
        default="{1:'Bayview',2:'Carling',3:'Carleton',4:'Confed',5:'Greenboro'}",
        help="Station name map as a Python dict literal string.",
    )
    parser.add_argument("--travel_time_s", type=int, default=225, help="Inter-station travel time in seconds.")
    parser.add_argument(
        "--route_sequence",
        type=str,
        default=(
            "[{'station_id':1,'direction':0},"
            "{'station_id':2,'direction':0},"
            "{'station_id':3,'direction':0},"
            "{'station_id':4,'direction':0},"
            "{'station_id':5,'direction':1},"
            "{'station_id':4,'direction':1},"
            "{'station_id':3,'direction':1},"
            "{'station_id':2,'direction':1},"
            "{'station_id':1,'direction':0}]"
        ),
        help="Route sequence as a Python list-of-dicts literal string.",
    )
    parser.add_argument(
        "--initial_train_arrival_time_s",
        type=float,
        default=0.0,
        help="Initial train arrival time at first stop in seconds.",
    )
    parser.add_argument(
        "--service_dt_s",
        type=float,
        default=0.025,
        help="Serial service time step in seconds for boarding/alighting.",
    )
    parser.add_argument(
        "--init_passenger_time_s",
        type=float,
        default=0.5,
        help="Time to generate initialization passenger at every station in seconds.",
    )
    parser.add_argument(
        "--gen_mean_min",
        type=float,
        default=5.0,
        help="Passenger inter-arrival Normal mean in minutes.",
    )
    parser.add_argument(
        "--gen_std_min",
        type=float,
        default=5.0,
        help="Passenger inter-arrival Normal stddev in minutes.",
    )
    parser.add_argument(
        "--gen_clamp_min_min",
        type=int,
        default=1,
        help="Lower clamp bound for inter-arrival in minutes.",
    )
    parser.add_argument(
        "--gen_clamp_max_min",
        type=int,
        default=9,
        help="Upper clamp bound for inter-arrival in minutes.",
    )

    args = parser.parse_args()

    # Seed RNG using system time (do not use real-time pacing; only affects stochastic generation)
    random.seed(time.time_ns())

    # Parse runner horizon
    simulate_time = parse_hhmmssmmm_to_seconds(args.simulate_time)

    # Parse dict/list literals from strings without importing non-allowed libraries.
    # (Using eval with no builtins to keep it constrained to literals.)
    station_names = eval(args.station_names, {"__builtins__": {}}, {})
    route_sequence = eval(args.route_sequence, {"__builtins__": {}}, {})

    # Step 3.1: Create the clock
    clock = SimulationClock()
    # Step 3.2: Register the clock globally
    set_global_clock(clock)

    # Step 3.3: Instantiate the model
    model = OTrain(
        name=args.name,
        parent=None,
        station_ids=list(args.station_ids),
        station_names=station_names,
        travel_time_s=args.travel_time_s,
        route_sequence=route_sequence,
        initial_train_arrival_time_s=args.initial_train_arrival_time_s,
        service_dt_s=args.service_dt_s,
        init_passenger_time_s=args.init_passenger_time_s,
        gen_mean_min=args.gen_mean_min,
        gen_std_min=args.gen_std_min,
        gen_clamp_min_min=args.gen_clamp_min_min,
        gen_clamp_max_min=args.gen_clamp_max_min,
    )

    # Step 3.4: Create the simulator
    sim = Coordinator(model, clock)

    # Step 4: Simulation execution
    sim.initialize()
    # Treat CLI duration as an observation horizon; include boundary events if any.
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()