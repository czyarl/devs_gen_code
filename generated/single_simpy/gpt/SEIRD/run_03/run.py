#!/usr/bin/env python3
import argparse
import sys
import json
import logging
from typing import Dict, Any

import simpy

# xdevs is listed in requirements, but it may not be installed in all environments.
# Do not fail if unavailable.
try:
    import xdevs  # noqa: F401
except Exception as e:  # pragma: no cover
    xdevs = None
    # Logging configured in main; fallback safe write here:
    sys.stderr.write(f"[WARN] xdevs import failed (continuing without it): {e}\n")


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def round2(x: float) -> float:
    # Ensure JSON contains floats with 2 decimal places
    return float(f"{x:.2f}")


def validate_args(args: argparse.Namespace, log: logging.Logger) -> None:
    if args.total_population < 0:
        raise ValueError("--total_population must be >= 0")
    if args.initial_infective < 0:
        raise ValueError("--initial_infective must be >= 0")
    if args.initial_infective > args.total_population:
        raise ValueError("--initial_infective must be <= --total_population")
    if args.dt <= 0:
        raise ValueError("--dt must be > 0")
    if args.incubation_period <= 0:
        raise ValueError("--incubation_period must be > 0")
    if args.infectivity_period <= 0:
        raise ValueError("--infectivity_period must be > 0")
    if args.simulation_time < 0:
        raise ValueError("--simulation_time must be >= 0")
    if not (0.0 <= args.mortality <= 100.0):
        raise ValueError("--mortality must be in [0, 100]")
    if args.transmission_rate < 0:
        raise ValueError("--transmission_rate must be >= 0")
    if not args.test_name:
        raise ValueError("--test_name is required")

    log.debug("Arguments validated successfully.")


def seird_step(state: Dict[str, float], params: Dict[str, float], dt: float, log: logging.Logger) -> None:
    """
    One SEIRD Euler step with the rules specified, including safe caps to prevent
    negative compartments when dt is large.
    Mutates `state` in-place.
    """
    S = state["susceptible"]
    E = state["exposed"]
    I = state["infective"]
    R = state["recovered"]
    D = state["deceased"]

    N = params["total_population"]
    beta = params["transmission_rate"]
    incubation_period = params["incubation_period"]
    infectivity_period = params["infectivity_period"]
    mortality = params["mortality"] / 100.0

    # S -> E
    if N > 0.0:
        new_exposed = (beta * S * I / N) * dt
    else:
        new_exposed = 0.0
    new_exposed = min(new_exposed, S)

    # E -> I
    new_infective = (E / incubation_period) * dt
    new_infective = min(new_infective, E)

    # I -> R, I -> D
    # Raw flows
    raw_outflow = (I / infectivity_period) * dt if infectivity_period > 0 else 0.0
    # Prevent outflow exceeding available infective
    outflow = min(raw_outflow, I)

    new_deceased = outflow * mortality
    new_recovered = outflow * (1.0 - mortality)

    # Updates
    S_new = S - new_exposed
    E_new = E + new_exposed - new_infective
    I_new = I + new_infective - new_deceased - new_recovered
    R_new = R + new_recovered
    D_new = D + new_deceased

    # Numerical safety clamps (should rarely be needed after caps above)
    S_new = max(0.0, S_new)
    E_new = max(0.0, E_new)
    I_new = max(0.0, I_new)
    R_new = max(0.0, R_new)
    D_new = max(0.0, D_new)

    state["susceptible"] = S_new
    state["exposed"] = E_new
    state["infective"] = I_new
    state["recovered"] = R_new
    state["deceased"] = D_new

    # Conservation check (within floating precision)
    total = S_new + E_new + I_new + R_new + D_new
    if abs(total - N) > 1e-6:
        log.debug(f"Population conservation deviation: total={total:.10f}, N={N:.10f}, diff={total - N:.10e}")


def seird_process(env: simpy.Environment, state: Dict[str, float], params: Dict[str, float],
                  dt: float, simulation_time: float, log: logging.Logger):
    while env.now + 1e-12 < simulation_time:
        dt_step = min(dt, simulation_time - env.now)
        seird_step(state, params, dt_step, log)
        yield env.timeout(dt_step)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SEIRD discrete-time simulation (teaching demo).")
    p.add_argument("--test_name", type=str, required=True, help="Name of the test case being run.")
    p.add_argument("--mortality", type=float, default=10.0, help="Mortality rate percentage (0-100).")
    p.add_argument("--infectivity_period", type=float, default=14.0, help="Average infectious period (days).")
    p.add_argument("--dt", type=float, default=0.1, help="Time step (days).")
    p.add_argument("--incubation_period", type=float, default=5.0, help="Average incubation period (days).")
    p.add_argument("--total_population", type=int, default=1000, help="Total population size (>=0).")
    p.add_argument("--initial_infective", type=int, default=10, help="Initial infective count.")
    p.add_argument("--transmission_rate", type=float, default=2.5, help="Transmission rate beta per day.")
    p.add_argument("--simulation_time", type=float, default=10.0, help="Total simulation time (days).")
    p.add_argument("--log_level", type=str, default="WARNING",
                   help="Logging level to stderr (DEBUG, INFO, WARNING, ERROR).")
    return p


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.WARNING),
        format="%(levelname)s:%(name)s:%(message)s",
        stream=sys.stderr,
    )
    log = logging.getLogger("seird_sim")

    try:
        validate_args(args, log)
    except Exception as e:
        log.error(str(e))
        return 2

    N = float(args.total_population)
    I0 = float(args.initial_infective)

    # Initial state
    state: Dict[str, float] = {
        "susceptible": max(0.0, N - I0),
        "exposed": 0.0,
        "infective": I0,
        "recovered": 0.0,
        "deceased": 0.0,
    }

    params: Dict[str, float] = {
        "total_population": N,
        "mortality": float(args.mortality),
        "infectivity_period": float(args.infectivity_period),
        "incubation_period": float(args.incubation_period),
        "transmission_rate": float(args.transmission_rate),
    }

    env = simpy.Environment(initial_time=0.0)
    env.process(seird_process(env, state, params, float(args.dt), float(args.simulation_time), log))
    env.run(until=float(args.simulation_time) if args.simulation_time > 0 else 0.0)

    out: Dict[str, Any] = {
        "time": round2(float(env.now)),
        "susceptible": round2(state["susceptible"]),
        "exposed": round2(state["exposed"]),
        "infective": round2(state["infective"]),
        "recovered": round2(state["recovered"]),
        "deceased": round2(state["deceased"]),
    }

    # stdout must be JSONL only
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())