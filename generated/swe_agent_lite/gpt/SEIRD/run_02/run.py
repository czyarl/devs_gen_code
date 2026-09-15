#!/usr/bin/env python3
"""SEIRD epidemic compartmental model simulated with Discrete Event Simulation (SimPy).

Outputs ONLY a single JSONL object to stdout containing the final state.
All logs/debug information goes to stderr.

Model details follow the PR description.
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


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SEIRD DES simulation (SimPy)")

    p.add_argument("--test_name", type=str, required=True, help="Name of the test case")
    p.add_argument("--mortality", type=float, default=10.0, help="Mortality rate percentage (0-100)")
    p.add_argument(
        "--infectivity_period",
        type=float,
        default=14.0,
        help="Average days a person stays infectious",
    )
    p.add_argument("--dt", type=float, default=0.1, help="Time step in days")
    p.add_argument(
        "--incubation_period",
        type=float,
        default=5.0,
        help="Average days from exposure to becoming infectious",
    )
    p.add_argument("--total_population", type=int, default=1000, help="Total population size")
    p.add_argument("--initial_infective", type=int, default=10, help="Initial infective count")
    p.add_argument(
        "--transmission_rate",
        type=float,
        default=2.5,
        help="Transmission rate beta per day",
    )
    p.add_argument("--simulation_time", type=float, default=10.0, help="Total simulation time in days")

    args = p.parse_args(argv)

    # Basic validation (log warnings/errors to stderr)
    if args.total_population < 0:
        p.error("--total_population must be >= 0")
    if args.initial_infective < 0:
        p.error("--initial_infective must be >= 0")
    if args.initial_infective > args.total_population:
        p.error("--initial_infective cannot exceed --total_population")
    if args.dt <= 0:
        p.error("--dt must be > 0")
    if args.simulation_time < 0:
        p.error("--simulation_time must be >= 0")
    if args.infectivity_period <= 0:
        p.error("--infectivity_period must be > 0")
    if args.incubation_period <= 0:
        p.error("--incubation_period must be > 0")
    if not (0.0 <= args.mortality <= 100.0):
        p.error("--mortality must be between 0 and 100")

    return args


def seird_step(state: SEIRDState, *, beta: float, n: float, incubation_period: float, infectivity_period: float, mortality_pct: float, dt: float) -> SEIRDState:
    """Compute one Euler step according to the specification."""

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


def seird_process(env: simpy.Environment, state: SEIRDState, params: argparse.Namespace):
    """SimPy process that advances the SEIRD state every dt until simulation_time."""

    n = float(params.total_population)
    t_end = float(params.simulation_time)
    dt = float(params.dt)

    # Advance in fixed increments; last step may be shorter to land exactly on t_end.
    while env.now + 1e-12 < t_end:
        step_dt = dt
        if env.now + step_dt > t_end:
            step_dt = t_end - env.now

        # Update state at the *start* of the interval using old values (Euler)
        new_state = seird_step(
            state,
            beta=float(params.transmission_rate),
            n=n,
            incubation_period=float(params.incubation_period),
            infectivity_period=float(params.infectivity_period),
            mortality_pct=float(params.mortality),
            dt=step_dt,
        )

        state.s, state.e, state.i, state.r, state.d = new_state.s, new_state.e, new_state.i, new_state.r, new_state.d

        yield env.timeout(step_dt)


def main(argv: list[str]) -> int:
    _setup_logging()
    args = parse_args(argv)

    # Initial state
    n = float(args.total_population)
    i0 = float(args.initial_infective)
    state = SEIRDState(s=n - i0, e=0.0, i=i0, r=0.0, d=0.0)

    env = simpy.Environment(initial_time=0.0)
    env.process(seird_process(env, state, args))
    env.run(until=float(args.simulation_time))

    # Output final state as JSONL to stdout ONLY
    out = {
        "time": float(f"{float(args.simulation_time):.2f}"),
        "susceptible": float(f"{state.s:.2f}"),
        "exposed": float(f"{state.e:.2f}"),
        "infective": float(f"{state.i:.2f}"),
        "recovered": float(f"{state.r:.2f}"),
        "deceased": float(f"{state.d:.2f}"),
    }
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
