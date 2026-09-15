#!/usr/bin/env python3
"""SEIRD compartmental model simulated with Discrete Event Simulation (SimPy).

Outputs ONLY a single JSONL object to stdout containing the final state.
All logs/debug go to stderr.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass

import simpy


@dataclass
class SEIRDState:
    s: float
    e: float
    i: float
    r: float
    d: float


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SEIRD epidemic model (DES via SimPy)")
    p.add_argument("--test_name", type=str, required=True, help="Name of the test case being run")
    p.add_argument("--mortality", type=float, default=10.0, help="Mortality rate as percentage (0-100)")
    p.add_argument(
        "--infectivity_period",
        type=float,
        default=14.0,
        help="Average days a person stays infectious",
    )
    p.add_argument("--dt", type=float, default=0.1, help="Time step for numerical integration in days")
    p.add_argument(
        "--incubation_period",
        type=float,
        default=5.0,
        help="Average days from exposure to becoming infectious",
    )
    p.add_argument("--total_population", type=int, default=1000, help="Total population size (integer >= 0)")
    p.add_argument("--initial_infective", type=int, default=10, help="Initial number of infected individuals")
    p.add_argument("--transmission_rate", type=float, default=2.5, help="Transmission rate (beta) per day")
    p.add_argument("--simulation_time", type=float, default=10.0, help="Total simulation time in days")
    return p


def validate_args(args: argparse.Namespace) -> None:
    if args.total_population < 0:
        raise SystemExit("--total_population must be >= 0")
    if args.initial_infective < 0:
        raise SystemExit("--initial_infective must be >= 0")
    if args.initial_infective > args.total_population:
        raise SystemExit("--initial_infective must be <= --total_population")
    if args.dt <= 0:
        raise SystemExit("--dt must be > 0")
    if args.simulation_time < 0:
        raise SystemExit("--simulation_time must be >= 0")
    if args.infectivity_period <= 0:
        raise SystemExit("--infectivity_period must be > 0")
    if args.incubation_period <= 0:
        raise SystemExit("--incubation_period must be > 0")
    if not (0.0 <= args.mortality <= 100.0):
        raise SystemExit("--mortality must be between 0 and 100")


def seird_step(state: SEIRDState, *, beta: float, n: float, incubation_period: float, infectivity_period: float, mortality_pct: float, dt: float) -> SEIRDState:
    """One Euler step according to the specification."""
    s_old, e_old, i_old, r_old, d_old = state.s, state.e, state.i, state.r, state.d

    # S -> E
    new_exposed = (beta * s_old * i_old / n) * dt if n > 0 else 0.0
    if new_exposed > s_old:
        new_exposed = s_old

    # E -> I
    new_infective = (e_old / incubation_period) * dt
    if new_infective > e_old:
        new_infective = e_old

    # I -> R / D
    mort = mortality_pct / 100.0
    new_deceased = (i_old / infectivity_period) * mort * dt
    new_recovered = (i_old / infectivity_period) * (1.0 - mort) * dt

    s_new = s_old - new_exposed
    e_new = e_old + new_exposed - new_infective
    i_new = i_old + new_infective - new_deceased - new_recovered
    r_new = r_old + new_recovered
    d_new = d_old + new_deceased

    # Guard against tiny negative values due to floating point
    def clamp0(x: float) -> float:
        return x if x >= 0.0 else 0.0

    return SEIRDState(clamp0(s_new), clamp0(e_new), clamp0(i_new), clamp0(r_new), clamp0(d_new))


def seird_process(env: simpy.Environment, state_box: dict, params: dict) -> simpy.events.Event:
    """SimPy process that updates the SEIRD state every dt until simulation_time."""
    dt = params["dt"]
    sim_time = params["simulation_time"]

    # Run updates at t=0, dt, 2dt, ... <= sim_time
    while env.now + 1e-12 < sim_time:
        state_box["state"] = seird_step(state_box["state"], **params)
        yield env.timeout(dt)

    # If sim_time is not an exact multiple of dt, do one final partial step to land exactly on sim_time.
    remaining = sim_time - env.now
    if remaining > 1e-12:
        p2 = dict(params)
        p2["dt"] = remaining
        state_box["state"] = seird_step(state_box["state"], **p2)
        yield env.timeout(remaining)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    validate_args(args)

    n = float(args.total_population)
    init_i = float(args.initial_infective)

    state = SEIRDState(
        s=n - init_i,
        e=0.0,
        i=init_i,
        r=0.0,
        d=0.0,
    )

    env = simpy.Environment(initial_time=0.0)
    state_box = {"state": state}

    params = {
        "beta": float(args.transmission_rate),
        "n": n,
        "incubation_period": float(args.incubation_period),
        "infectivity_period": float(args.infectivity_period),
        "mortality_pct": float(args.mortality),
        "dt": float(args.dt),
        "simulation_time": float(args.simulation_time),
    }

    env.process(seird_process(env, state_box, params))
    env.run(until=float(args.simulation_time))

    final_state: SEIRDState = state_box["state"]

    out = {
        "time": float(f"{env.now:.2f}"),
        "susceptible": float(f"{final_state.s:.2f}"),
        "exposed": float(f"{final_state.e:.2f}"),
        "infective": float(f"{final_state.i:.2f}"),
        "recovered": float(f"{final_state.r:.2f}"),
        "deceased": float(f"{final_state.d:.2f}"),
    }

    sys.stdout.write(json.dumps(out) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
