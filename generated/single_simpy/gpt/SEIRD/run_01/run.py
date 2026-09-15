#!/usr/bin/env python3
import argparse
import sys
import json
import logging
from typing import Dict

import simpy

# Optional dependency (not required for this simulation, but listed in requirements)
try:
    import xdevs  # noqa: F401
except Exception:
    xdevs = None  # type: ignore


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SEIRD discrete-time simulation (Euler integration).")

    p.add_argument("--test_name", type=str, required=True, help="Name of the test case being run.")

    p.add_argument("--mortality", type=float, default=10.0, help="Mortality rate as percentage (0-100).")
    p.add_argument("--infectivity_period", type=float, default=14.0, help="Average days a person stays infectious.")
    p.add_argument("--dt", type=float, default=0.1, help="Time step for numerical integration in days.")
    p.add_argument("--incubation_period", type=float, default=5.0, help="Average days from exposure to infectious.")
    p.add_argument("--total_population", type=int, default=1000, help="Total population size (integer >= 0).")
    p.add_argument("--initial_infective", type=int, default=10, help="Initial number of infective individuals.")
    p.add_argument("--transmission_rate", type=float, default=2.5, help="Transmission rate (beta) per day.")
    p.add_argument("--simulation_time", type=float, default=10.0, help="Total simulation time in days.")

    args = p.parse_args(argv)

    # Basic validation
    if args.total_population < 0:
        p.error("--total_population must be >= 0")
    if args.initial_infective < 0:
        p.error("--initial_infective must be >= 0")
    if args.mortality < 0.0 or args.mortality > 100.0:
        p.error("--mortality must be between 0 and 100")
    if args.infectivity_period <= 0.0:
        p.error("--infectivity_period must be > 0")
    if args.incubation_period <= 0.0:
        p.error("--incubation_period must be > 0")
    if args.dt <= 0.0:
        p.error("--dt must be > 0")
    if args.simulation_time < 0.0:
        p.error("--simulation_time must be >= 0")
    if args.transmission_rate < 0.0:
        p.error("--transmission_rate must be >= 0")

    return args


def seird_step(state: Dict[str, float], params: Dict[str, float], dt: float) -> Dict[str, float]:
    """
    One Euler step with the specified discrete-time update rules.
    """
    S_old = state["susceptible"]
    E_old = state["exposed"]
    I_old = state["infective"]
    R_old = state["recovered"]
    D_old = state["deceased"]

    N = params["total_population"]
    beta = params["transmission_rate"]
    incubation_period = params["incubation_period"]
    infectivity_period = params["infectivity_period"]
    mortality = params["mortality"] / 100.0

    # S -> E
    if N > 0.0:
        new_exposed = (beta * S_old * I_old / N) * dt
    else:
        new_exposed = 0.0
    if new_exposed > S_old:
        new_exposed = S_old
    if new_exposed < 0.0:
        new_exposed = 0.0
    S_new = S_old - new_exposed

    # E -> I
    new_infective = (E_old / incubation_period) * dt
    if new_infective > E_old:
        new_infective = E_old
    if new_infective < 0.0:
        new_infective = 0.0
    E_new = E_old + new_exposed - new_infective

    # I -> R and I -> D
    new_deceased = (I_old / infectivity_period) * mortality * dt
    new_recovered = (I_old / infectivity_period) * (1.0 - mortality) * dt

    # Guard against numerical issues
    if new_deceased < 0.0:
        new_deceased = 0.0
    if new_recovered < 0.0:
        new_recovered = 0.0
    # Ensure we don't remove more than I_old in total due to rounding
    total_out = new_deceased + new_recovered
    if total_out > I_old and total_out > 0.0:
        scale = I_old / total_out
        new_deceased *= scale
        new_recovered *= scale

    I_new = I_old + new_infective - new_deceased - new_recovered
    R_new = R_old + new_recovered
    D_new = D_old + new_deceased

    # Clamp tiny negatives caused by floating point arithmetic
    def clamp(x: float) -> float:
        return 0.0 if x < 0.0 and abs(x) < 1e-12 else x

    S_new = clamp(S_new)
    E_new = clamp(E_new)
    I_new = clamp(I_new)
    R_new = clamp(R_new)
    D_new = clamp(D_new)

    return {
        "susceptible": S_new,
        "exposed": E_new,
        "infective": I_new,
        "recovered": R_new,
        "deceased": D_new,
    }


def run_simulation(args: argparse.Namespace) -> Dict[str, float]:
    N = float(args.total_population)
    I0 = float(min(args.initial_infective, args.total_population)) if args.total_population > 0 else 0.0

    state = {
        "susceptible": max(N - I0, 0.0),
        "exposed": 0.0,
        "infective": I0,
        "recovered": 0.0,
        "deceased": 0.0,
    }

    params = {
        "total_population": N,
        "transmission_rate": float(args.transmission_rate),
        "incubation_period": float(args.incubation_period),
        "infectivity_period": float(args.infectivity_period),
        "mortality": float(args.mortality),
    }

    env = simpy.Environment()

    def process():
        nonlocal state
        # Start at time 0.0 immediately
        while env.now + 1e-12 < args.simulation_time:
            step = min(float(args.dt), float(args.simulation_time) - float(env.now))
            # Update state based on current values
            state = seird_step(state, params, step)
            yield env.timeout(step)

    env.process(process())
    env.run(until=float(args.simulation_time))

    # Enforce conservation within floating point precision (optional corrective tiny adjustment)
    total = sum(state.values())
    if N > 0.0 and abs(total - N) > 1e-6:
        # Adjust susceptible to absorb tiny drift
        state["susceptible"] += (N - total)

    result = {
        "time": float(args.simulation_time),
        "susceptible": float(round(state["susceptible"], 2)),
        "exposed": float(round(state["exposed"], 2)),
        "infective": float(round(state["infective"], 2)),
        "recovered": float(round(state["recovered"], 2)),
        "deceased": float(round(state["deceased"], 2)),
    }
    # Ensure time has at least two decimals conceptually (as float)
    result["time"] = float(round(result["time"], 2))
    return result


def main(argv=None) -> int:
    setup_logging()
    args = parse_args(argv)

    logging.info(
        "Running SEIRD simulation test_name=%s N=%d I0=%d beta=%.6g dt=%.6g T=%.6g",
        args.test_name,
        args.total_population,
        args.initial_infective,
        args.transmission_rate,
        args.dt,
        args.simulation_time,
    )

    final_state = run_simulation(args)

    # stdout MUST be JSONL only
    sys.stdout.write(json.dumps(final_state) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())