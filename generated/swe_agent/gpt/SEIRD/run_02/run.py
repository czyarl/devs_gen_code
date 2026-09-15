#!/usr/bin/env python3
"""SEIRD discrete-time simulation using a DES engine (simpy).

Entry point: run.py

Implements the PR requirements:
- Python 3.10+
- argparse CLI
- JSONL to stdout (final state only)
- logs to stderr
- uses a DES tool (simpy) to advance time in fixed increments dt
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass

import simpy


LOG = logging.getLogger(__name__)


def _float2(x: float) -> float:
    """Format to 2 decimals while keeping float type."""
    return float(f"{x:.2f}")


@dataclass
class SEIRDState:
    susceptible: float
    exposed: float
    infective: float
    recovered: float
    deceased: float


class SEIRDSimulator:
    def __init__(
        self,
        *,
        total_population: int,
        initial_infective: int,
        transmission_rate: float,
        incubation_period: float,
        infectivity_period: float,
        mortality: float,
    ) -> None:
        self.total_population = float(max(0, total_population))
        i0 = float(max(0, min(initial_infective, int(self.total_population))))

        self.transmission_rate = float(transmission_rate)
        self.incubation_period = float(incubation_period)
        self.infectivity_period = float(infectivity_period)
        self.mortality = float(mortality)

        self.state = SEIRDState(
            susceptible=float(self.total_population - i0),
            exposed=0.0,
            infective=i0,
            recovered=0.0,
            deceased=0.0,
        )

    def step(self, dt: float) -> None:
        """Advance the model by one timestep dt (days)."""
        s = self.state.susceptible
        e = self.state.exposed
        i = self.state.infective
        r = self.state.recovered
        d = self.state.deceased

        n = self.total_population
        if n <= 0.0:
            self.state = SEIRDState(0.0, 0.0, 0.0, 0.0, 0.0)
            return

        beta = self.transmission_rate
        incubation = self.incubation_period
        infectious = self.infectivity_period
        mort_frac = max(0.0, min(100.0, self.mortality)) / 100.0

        # S -> E
        new_exposed = (beta * s * i / n) * dt
        new_exposed = max(0.0, min(new_exposed, s))
        s_new = s - new_exposed

        # E -> I
        if incubation <= 0.0:
            new_infective = e
        else:
            new_infective = (e / incubation) * dt
        new_infective = max(0.0, min(new_infective, e))
        e_new = e + new_exposed - new_infective

        # I -> R, D
        if infectious <= 0.0:
            new_deceased = i * mort_frac
            new_recovered = i * (1.0 - mort_frac)
        else:
            new_deceased = (i / infectious) * mort_frac * dt
            new_recovered = (i / infectious) * (1.0 - mort_frac) * dt

        # Prevent leaving more than available I.
        total_out = new_deceased + new_recovered
        if total_out > i and total_out > 0.0:
            scale = i / total_out
            new_deceased *= scale
            new_recovered *= scale

        i_new = i + new_infective - new_deceased - new_recovered
        r_new = r + new_recovered
        d_new = d + new_deceased

        # Clip tiny negatives from floating point.
        def clip0(x: float) -> float:
            return 0.0 if x < 0.0 and abs(x) < 1e-12 else x

        self.state = SEIRDState(
            clip0(s_new),
            clip0(e_new),
            clip0(i_new),
            clip0(r_new),
            clip0(d_new),
        )


def _simulate_with_simpy(sim: SEIRDSimulator, *, dt: float, simulation_time: float) -> float:
    """Run using simpy and return the final absolute time.

    simpy requires `until` to be strictly greater than the current env time.
    When simulation_time == 0, we should simply skip running the environment.
    """
    simulation_time = float(simulation_time)
    if simulation_time <= 0.0:
        return 0.0

    env = simpy.Environment()

    def runner():
        # Update at end of each dt interval.
        while env.now + 1e-12 < simulation_time:
            step_dt = min(dt, simulation_time - env.now)
            yield env.timeout(step_dt)
            sim.step(step_dt)

    env.process(runner())
    env.run(until=simulation_time)
    return float(simulation_time)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SEIRD Epidemic Compartmental Model (DES)")
    p.add_argument("--test_name", type=str, required=True)
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
        level=logging.WARNING,
        stream=sys.stderr,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    args = build_arg_parser().parse_args(argv)

    if args.dt <= 0:
        raise SystemExit("--dt must be > 0")
    if args.simulation_time < 0:
        raise SystemExit("--simulation_time must be >= 0")
    if args.total_population < 0:
        raise SystemExit("--total_population must be >= 0")

    sim = SEIRDSimulator(
        total_population=args.total_population,
        initial_infective=args.initial_infective,
        transmission_rate=args.transmission_rate,
        incubation_period=args.incubation_period,
        infectivity_period=args.infectivity_period,
        mortality=args.mortality,
    )

    final_time = _simulate_with_simpy(sim, dt=float(args.dt), simulation_time=float(args.simulation_time))

    st = sim.state
    output = {
        "time": float(f"{final_time:.2f}"),
        "susceptible": _float2(st.susceptible),
        "exposed": _float2(st.exposed),
        "infective": _float2(st.infective),
        "recovered": _float2(st.recovered),
        "deceased": _float2(st.deceased),
    }
    print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
