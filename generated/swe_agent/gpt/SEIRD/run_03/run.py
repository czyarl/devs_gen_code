#!/usr/bin/env python3
"""SEIRD compartmental model simulation using discrete-event simulation (SimPy).

Implements the interface and calculation rules described in the PR:
- Python 3.10+
- argparse-based CLI
- JSONL output on stdout (final state)
- Any logs/errors on stderr
- Uses DES (simpy) for time advancement

No stdin is required.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass

import simpy


LOG = logging.getLogger(__name__)


def _float_2(x: float) -> float:
    """Return x rounded to 2 decimal places, as a float (not a string)."""
    return float(f"{x:.2f}")


@dataclass
class SEIRDState:
    susceptible: float
    exposed: float
    infective: float
    recovered: float
    deceased: float


def step_seird(
    state: SEIRDState,
    *,
    beta: float,
    n_total: float,
    incubation_period: float,
    infectivity_period: float,
    mortality_pct: float,
    dt: float,
) -> SEIRDState:
    """Advance SEIRD state by one time step dt following the PR formulas."""

    s_old, e_old, i_old, r_old, d_old = (
        state.susceptible,
        state.exposed,
        state.infective,
        state.recovered,
        state.deceased,
    )

    # S -> E
    new_exposed = (beta * s_old * i_old / n_total) * dt if n_total > 0 else 0.0
    new_exposed = min(new_exposed, s_old)

    # E -> I
    new_infective = (e_old / incubation_period) * dt if incubation_period > 0 else 0.0
    new_infective = min(new_infective, e_old)

    # I -> R / D
    mort = mortality_pct / 100.0
    if infectivity_period > 0:
        new_deceased = (i_old / infectivity_period) * mort * dt
        new_recovered = (i_old / infectivity_period) * (1.0 - mort) * dt
    else:
        new_deceased = 0.0
        new_recovered = 0.0

    s_new = s_old - new_exposed
    e_new = e_old + new_exposed - new_infective
    i_new = i_old + new_infective - new_deceased - new_recovered
    r_new = r_old + new_recovered
    d_new = d_old + new_deceased

    # Avoid tiny negative values from floating-point arithmetic.
    def clamp0(x: float) -> float:
        return x if x > 0.0 else 0.0

    return SEIRDState(
        susceptible=clamp0(s_new),
        exposed=clamp0(e_new),
        infective=clamp0(i_new),
        recovered=clamp0(r_new),
        deceased=clamp0(d_new),
    )


def simulate(
    *,
    mortality: float,
    infectivity_period: float,
    dt: float,
    incubation_period: float,
    total_population: int,
    initial_infective: int,
    transmission_rate: float,
    simulation_time: float,
) -> tuple[float, SEIRDState]:
    """Run a SEIRD simulation until simulation_time and return (time, final_state)."""

    if total_population < 0:
        raise ValueError("total_population must be >= 0")
    if initial_infective < 0:
        raise ValueError("initial_infective must be >= 0")
    if initial_infective > total_population:
        raise ValueError("initial_infective must be <= total_population")
    if not (0.0 <= mortality <= 100.0):
        raise ValueError("mortality must be between 0 and 100")
    if dt <= 0.0:
        raise ValueError("dt must be > 0")
    if simulation_time < 0.0:
        raise ValueError("simulation_time must be >= 0")
    if incubation_period <= 0.0:
        raise ValueError("incubation_period must be > 0")
    if infectivity_period <= 0.0:
        raise ValueError("infectivity_period must be > 0")

    n_total = float(total_population)
    i0 = float(initial_infective)

    env = simpy.Environment()

    state = SEIRDState(
        susceptible=n_total - i0,
        exposed=0.0,
        infective=i0,
        recovered=0.0,
        deceased=0.0,
    )

    def _process():
        nonlocal state
        while env.now + 1e-12 < simulation_time:
            remaining = simulation_time - env.now
            step = dt if dt <= remaining else remaining
            state = step_seird(
                state,
                beta=transmission_rate,
                n_total=n_total,
                incubation_period=incubation_period,
                infectivity_period=infectivity_period,
                mortality_pct=mortality,
                dt=step,
            )
            yield env.timeout(step)

    env.process(_process())
    env.run(until=simulation_time)

    return float(simulation_time), state


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SEIRD Epidemic Model (SimPy DES)")
    p.add_argument("--test_name", type=str, required=True, help="Name of the test case")
    p.add_argument("--mortality", type=float, default=10.0)
    p.add_argument("--infectivity_period", type=float, default=14.0)
    p.add_argument("--dt", type=float, default=0.1)
    p.add_argument("--incubation_period", type=float, default=5.0)
    p.add_argument("--total_population", type=int, default=1000)
    p.add_argument("--initial_infective", type=int, default=10)
    p.add_argument("--transmission_rate", type=float, default=2.5)
    p.add_argument("--simulation_time", type=float, default=10.0)
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    args = build_arg_parser().parse_args(argv)

    # test_name is accepted to match the required interface.
    LOG.debug("test_name=%s", args.test_name)

    try:
        t_final, final_state = simulate(
            mortality=args.mortality,
            infectivity_period=args.infectivity_period,
            dt=args.dt,
            incubation_period=args.incubation_period,
            total_population=args.total_population,
            initial_infective=args.initial_infective,
            transmission_rate=args.transmission_rate,
            simulation_time=args.simulation_time,
        )
    except Exception as exc:
        # Errors must go to stderr, and stdout should remain JSON-only.
        LOG.error("%s", exc)
        return 2

    result = {
        "time": _float_2(t_final),
        "susceptible": _float_2(final_state.susceptible),
        "exposed": _float_2(final_state.exposed),
        "infective": _float_2(final_state.infective),
        "recovered": _float_2(final_state.recovered),
        "deceased": _float_2(final_state.deceased),
    }

    sys.stdout.write(json.dumps(result) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
