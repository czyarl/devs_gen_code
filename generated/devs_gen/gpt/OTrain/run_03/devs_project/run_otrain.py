import argparse
import json
import logging
import sys
import time
import random

from xdevs.sim import Coordinator, SimulationClock
from devs_project.devs_utils.devs_context import set_global_clock

# The evaluator launches this runner with ``python -m package.run``.
# The leading dot keeps the model import inside that generated package.
from .OTrain import OTrain


def _parse_hhmmssmmm_to_seconds(value: str) -> float:
    """
    Parse duration formatted as 'HH:MM:SS:mmm' into seconds (float).
    Example: '00:01:00:000' -> 60.0
    """
    parts = value.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"simulate_time must be in 'HH:MM:SS:mmm' format, got: {value!r}")
    hh_s, mm_s, ss_s, mmm_s = parts
    hh = int(hh_s)
    mm = int(mm_s)
    ss = int(ss_s)
    mmm = int(mmm_s)
    if hh < 0 or mm < 0 or ss < 0 or mmm < 0:
        raise ValueError(f"simulate_time parts must be non-negative, got: {value!r}")
    if mm >= 60 or ss >= 60 or mmm >= 1000:
        raise ValueError(f"simulate_time out of range (MM<60, SS<60, mmm<1000), got: {value!r}")
    return float(hh * 3600 + mm * 60 + ss) + (mmm / 1000.0)


def _json_arg(value: str):
    """
    Parse a JSON string from CLI into a Python object.
    """
    try:
        return json.loads(value)
    except json.JSONDecodeError as e:
        raise argparse.ArgumentTypeError(f"Invalid JSON: {e}") from e


if __name__ == "__main__":
    # All non-business output must go to stderr
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(levelname)s: %(message)s")

    # Seed RNGs from system time (as required)
    seed = time.time_ns()
    random.seed(seed)
    try:
        import numpy as np  # optional; if available, seed it too
        np.random.seed(seed % (2**32 - 1))
    except Exception:
        pass

    # -----------------------------
    # 2. Configuration (ArgParse)
    # -----------------------------
    parser = argparse.ArgumentParser(description="Run OTrain DEVS simulation (xdevs)")

    # Runner-only stop horizon argument (scenario-specified name)
    parser.add_argument(
        "--simulate_time",
        type=str,
        default="00:01:00:000",
        help="Simulation duration in HH:MM:SS:mmm (default: 00:01:00:000).",
    )

    # OTrain model init args (exactly as specified)
    parser.add_argument("--name", type=str, default="OTrain", help="Model instance name")
    parser.add_argument("--parent", default=None, help="Framework parent reference or None (default: None)")

    parser.add_argument(
        "--station_ids",
        type=_json_arg,
        default=[1, 2, 3, 4, 5],
        help='JSON list of station IDs (default: [1,2,3,4,5])',
    )
    parser.add_argument(
        "--station_names",
        type=_json_arg,
        default={1: "Bayview", 2: "Carling", 3: "Carleton", 4: "Confed", 5: "Greenboro"},
        help='JSON dict mapping station_id to name (default: {1:"Bayview",2:"Carling",3:"Carleton",4:"Confed",5:"Greenboro"})',
    )
    parser.add_argument(
        "--train_travel_interval_s",
        type=float,
        default=225.0,
        help="Exact travel time between consecutive stations in seconds (default: 225.0)",
    )
    parser.add_argument(
        "--train_route_sequence",
        type=_json_arg,
        default=[
            {"station_id": 1, "direction": 0},
            {"station_id": 2, "direction": 0},
            {"station_id": 3, "direction": 0},
            {"station_id": 4, "direction": 0},
            {"station_id": 5, "direction": 1},
            {"station_id": 4, "direction": 1},
            {"station_id": 3, "direction": 1},
            {"station_id": 2, "direction": 1},
            {"station_id": 1, "direction": 0},
        ],
        help="JSON list of route stops (default: scenario constant sequence)",
    )
    parser.add_argument(
        "--passenger_init_time_s",
        type=float,
        default=0.5,
        help="Initialization passenger generation time in seconds (default: 0.5)",
    )
    parser.add_argument(
        "--passenger_interarrival_mean_min",
        type=float,
        default=5.0,
        help="Mean of Normal inter-arrival distribution in minutes (default: 5.0)",
    )
    parser.add_argument(
        "--passenger_interarrival_std_min",
        type=float,
        default=5.0,
        help="Std dev of Normal inter-arrival distribution in minutes (default: 5.0)",
    )
    parser.add_argument(
        "--passenger_interarrival_clamp_min_min",
        type=float,
        default=1.0,
        help="Lower clamp bound for sampled inter-arrival in minutes (default: 1.0)",
    )
    parser.add_argument(
        "--passenger_interarrival_clamp_max_min",
        type=float,
        default=9.0,
        help="Upper clamp bound for sampled inter-arrival in minutes (default: 9.0)",
    )
    parser.add_argument(
        "--boarding_alighting_step_s",
        type=float,
        default=0.025,
        help="Serial per-passenger delay for boarding and alighting in seconds (default: 0.025)",
    )

    args = parser.parse_args()

    simulate_time = _parse_hhmmssmmm_to_seconds(args.simulate_time)

    # -----------------------------
    # 3. Initialization (Strict)
    # -----------------------------
    clock = SimulationClock()
    set_global_clock(clock)

    model = OTrain(
        name=args.name,
        parent=args.parent,
        station_ids=args.station_ids,
        station_names=args.station_names,
        train_travel_interval_s=args.train_travel_interval_s,
        train_route_sequence=args.train_route_sequence,
        passenger_init_time_s=args.passenger_init_time_s,
        passenger_interarrival_mean_min=args.passenger_interarrival_mean_min,
        passenger_interarrival_std_min=args.passenger_interarrival_std_min,
        passenger_interarrival_clamp_min_min=args.passenger_interarrival_clamp_min_min,
        passenger_interarrival_clamp_max_min=args.passenger_interarrival_clamp_max_min,
        boarding_alighting_step_s=args.boarding_alighting_step_s,
    )

    sim = Coordinator(model, clock)

    # -----------------------------
    # 4. Simulation Execution
    # -----------------------------
    sim.initialize()
    # Treat CLI duration as an observation horizon; include boundary events.
    sim.simulate_time(simulate_time + 1e-9)
    sim.exit()