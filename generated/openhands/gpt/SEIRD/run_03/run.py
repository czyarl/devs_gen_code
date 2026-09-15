#!/usr/bin/env python3
"""SEIRD discrete-time epidemic model simulated via DES (SimPy).

Stdout: JSONL objects only.
Stderr: logs/debug.

Model:
  S -> E: beta * S * I / N
  E -> I: E / incubation_period
  I -> R/D: I / infectivity_period split by mortality

Updates use forward Euler with a fixed dt (or smaller final step).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import namedtuple

import simpy


LOG = logging.getLogger("seird")


SEIRDState = namedtuple(
    "SEIRDState",
    ["susceptible", "exposed", "infective", "recovered", "deceased"],
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SEIRD epidemic simulation (SimPy DES)")
    p.add_argument("--test_name", type=str, required=True, help="Name of the test case")

    p.add_argument("--mortality", type=float, default=10.0, help="Mortality rate percentage (0-100)")
    p.add_argument("--infectivity_period", type=float, default=14.0, help="Days a person stays infectious")
    p.add_argument("--dt", type=float, default=0.1, help="Time step in days")
    p.add_argument("--incubation_period", type=float, default=5.0, help="Days from exposure to infectious")
    p.add_argument("--total_population", type=int, default=1000, help="Total population (integer >= 0)")
    p.add_argument("--initial_infective", type=int, default=10, help="Initial infective individuals")
    p.add_argument("--transmission_rate", type=float, default=2.5, help="Transmission rate beta per day")
    p.add_argument("--simulation_time", type=float, default=10.0, help="Total simulation time in days")

    p.add_argument(
        "--log_level",
        type=str,
        default="WARNING",
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
        help="Logging level (stderr)",
    )
    return p


def _validate_args(a: argparse.Namespace) -> None:
    def die(msg: str) -> None:
        print(msg, file=sys.stderr)
        raise SystemExit(2)

    if not (0.0 <= a.mortality <= 100.0):
        die("--mortality must be between 0 and 100")
    if a.infectivity_period <= 0.0:
        die("--infectivity_period must be > 0")
    if a.incubation_period <= 0.0:
        die("--incubation_period must be > 0")
    if a.dt <= 0.0:
        die("--dt must be > 0")
    if a.simulation_time < 0.0:
        die("--simulation_time must be >= 0")
    if a.total_population < 0:
        die("--total_population must be >= 0")
    if a.initial_infective < 0:
        die("--initial_infective must be >= 0")
    if a.initial_infective > a.total_population:
        die("--initial_infective must be <= --total_population")
    if a.transmission_rate < 0.0:
        die("--transmission_rate must be >= 0")


def _step_update(
    state: SEIRDState,
    *,
    dt: float,
    total_population: float,
    beta: float,
    incubation_period: float,
    infectivity_period: float,
    mortality_pct: float,
) -> SEIRDState:
    """Compute one Euler step.

    Uses the calculation details in the prompt, with an additional safety cut so
    that I->(R,D) outflow does not exceed I in a single step.
    """

    S_old = state.susceptible
    E_old = state.exposed
    I_old = state.infective
    R_old = state.recovered
    D_old = state.deceased

    N = total_population
    mort_frac = mortality_pct / 100.0

    # S -> E
    if N > 0.0:
        new_exposed = (beta * S_old * I_old / N) * dt
    else:
        new_exposed = 0.0
    if new_exposed > S_old:
        new_exposed = S_old

    # E -> I
    new_infective = (E_old / incubation_period) * dt
    if new_infective > E_old:
        new_infective = E_old

    # I -> (R,D)
    outflow_total = (I_old / infectivity_period) * dt
    if outflow_total > I_old:
        # Numerical stability safety: don't remove more than exists.
        LOG.debug(
            "Cutting I outflow from %.6f to %.6f (dt=%.6f)", outflow_total, I_old, dt
        )
        outflow_total = I_old
    new_deceased = outflow_total * mort_frac
    new_recovered = outflow_total * (1.0 - mort_frac)

    S_new = S_old - new_exposed
    E_new = E_old + new_exposed - new_infective
    I_new = I_old + new_infective - new_deceased - new_recovered
    R_new = R_old + new_recovered
    D_new = D_old + new_deceased

    # Guard against tiny negative values due to FP.
    eps = 1e-12
    if S_new < 0 and S_new > -eps:
        S_new = 0.0
    if E_new < 0 and E_new > -eps:
        E_new = 0.0
    if I_new < 0 and I_new > -eps:
        I_new = 0.0
    if R_new < 0 and R_new > -eps:
        R_new = 0.0
    if D_new < 0 and D_new > -eps:
        D_new = 0.0

    return SEIRDState(
        susceptible=S_new,
        exposed=E_new,
        infective=I_new,
        recovered=R_new,
        deceased=D_new,
    )


def simulate(a: argparse.Namespace) -> tuple[float, SEIRDState]:
    env = simpy.Environment(initial_time=0.0)

    N = float(a.total_population)
    state = SEIRDState(
        susceptible=float(a.total_population - a.initial_infective),
        exposed=0.0,
        infective=float(a.initial_infective),
        recovered=0.0,
        deceased=0.0,
    )

    def tick_process():
        nonlocal state
        # Discrete-time updates scheduled as a DES process.
        while env.now + 1e-12 < a.simulation_time:
            dt_step = min(a.dt, a.simulation_time - env.now)
            state = _step_update(
                state,
                dt=dt_step,
                total_population=N,
                beta=a.transmission_rate,
                incubation_period=a.incubation_period,
                infectivity_period=a.infectivity_period,
                mortality_pct=a.mortality,
            )
            yield env.timeout(dt_step)

    env.process(tick_process())
    env.run(until=a.simulation_time)
    return float(env.now), state


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )

    _validate_args(args)

    t_final, state = simulate(args)

    # Stdout must contain ONLY JSONL objects.
    out = {
        "time": float(f"{t_final:.2f}"),
        "susceptible": float(f"{state.susceptible:.2f}"),
        "exposed": float(f"{state.exposed:.2f}"),
        "infective": float(f"{state.infective:.2f}"),
        "recovered": float(f"{state.recovered:.2f}"),
        "deceased": float(f"{state.deceased:.2f}"),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
