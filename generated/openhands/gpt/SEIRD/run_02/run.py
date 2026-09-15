#!/usr/bin/env python3
"""SEIRD discrete-time simulation using a Discrete Event Simulation engine (SimPy).

This script is intentionally minimal and CLI-driven for teaching/demonstration.
It performs an explicit Euler integration of the SEIRD compartmental model with
fixed time steps (dt) scheduled as events in a SimPy environment.

Stdout: JSONL with the final state only.
Stderr: logging/debug information.
"""

import argparse
import json
import logging
import sys
from collections import namedtuple

import simpy


SEIRDState = namedtuple("SEIRDState", ["s", "e", "i", "r", "d"])


class SEIRDSimulator:
    def __init__(
        self,
        env: simpy.Environment,
        *,
        total_population: int,
        transmission_rate: float,
        incubation_period: float,
        infectivity_period: float,
        mortality_pct: float,
        dt: float,
        simulation_time: float,
        initial_infective: int,
    ):
        self.env = env
        self.n = float(total_population)
        self.beta = float(transmission_rate)
        self.incubation_period = float(incubation_period)
        self.infectivity_period = float(infectivity_period)
        self.mortality = float(mortality_pct) / 100.0
        self.dt = float(dt)
        self.simulation_time = float(simulation_time)

        s0 = float(total_population - initial_infective)
        i0 = float(initial_infective)
        self.state = SEIRDState(s=s0, e=0.0, i=i0, r=0.0, d=0.0)

    def _step(self, dt_step: float) -> None:
        """Advance the model by dt_step using the provided transition equations."""
        st = self.state

        # Old state
        s_old, e_old, i_old, r_old, d_old = st.s, st.e, st.i, st.r, st.d

        # S -> E
        if self.n > 0.0:
            new_exposed = (self.beta * s_old * i_old / self.n) * dt_step
        else:
            new_exposed = 0.0
        if new_exposed > s_old:
            new_exposed = s_old
        if new_exposed < 0.0:
            new_exposed = 0.0

        # E -> I
        new_infective = (e_old / self.incubation_period) * dt_step
        if new_infective > e_old:
            new_infective = e_old
        if new_infective < 0.0:
            new_infective = 0.0

        # I -> R / D
        # Base outflow from I in dt_step
        total_out = (i_old / self.infectivity_period) * dt_step
        if total_out < 0.0:
            total_out = 0.0

        new_deceased = total_out * self.mortality
        new_recovered = total_out * (1.0 - self.mortality)

        # Safety clamp: ensure we don't remove more than exists due to large dt.
        removed = new_deceased + new_recovered
        if removed > i_old and removed > 0.0:
            scale = i_old / removed
            new_deceased *= scale
            new_recovered *= scale

        # New state
        s_new = s_old - new_exposed
        e_new = e_old + new_exposed - new_infective
        i_new = i_old + new_infective - new_deceased - new_recovered
        r_new = r_old + new_recovered
        d_new = d_old + new_deceased

        # Numerical hygiene (avoid tiny negatives)
        eps = 1e-12
        s_new = 0.0 if s_new < eps else s_new
        e_new = 0.0 if e_new < eps else e_new
        i_new = 0.0 if i_new < eps else i_new
        r_new = 0.0 if r_new < eps else r_new
        d_new = 0.0 if d_new < eps else d_new

        self.state = SEIRDState(s=s_new, e=e_new, i=i_new, r=r_new, d=d_new)

    def run(self):
        """SimPy process: schedule dt updates until simulation_time."""
        while self.env.now + 1e-12 < self.simulation_time:
            dt_step = min(self.dt, self.simulation_time - self.env.now)
            yield self.env.timeout(dt_step)
            self._step(dt_step)


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SEIRD epidemic model (SimPy DES)")

    p.add_argument("--test_name", type=str, required=True, help="Name of the test case")
    p.add_argument("--mortality", type=float, default=10.0, help="Mortality percentage (0-100)")
    p.add_argument("--infectivity_period", type=float, default=14.0, help="Days infectious")
    p.add_argument("--dt", type=float, default=0.1, help="Time step in days")
    p.add_argument("--incubation_period", type=float, default=5.0, help="Days from exposure to infectious")
    p.add_argument("--total_population", type=int, default=1000, help="Total population (>=0)")
    p.add_argument("--initial_infective", type=int, default=10, help="Initial infective count (>=0)")
    p.add_argument("--transmission_rate", type=float, default=2.5, help="Transmission rate beta per day")
    p.add_argument("--simulation_time", type=float, default=10.0, help="Total simulation time (days)")

    return p


def _validate_args(args: argparse.Namespace) -> None:
    def fail(msg: str) -> None:
        raise ValueError(msg)

    if args.total_population < 0:
        fail("--total_population must be >= 0")
    if args.initial_infective < 0:
        fail("--initial_infective must be >= 0")
    if args.initial_infective > args.total_population:
        fail("--initial_infective must be <= --total_population")

    if not (0.0 <= args.mortality <= 100.0):
        fail("--mortality must be within [0, 100]")

    if args.dt <= 0.0:
        fail("--dt must be > 0")
    if args.simulation_time < 0.0:
        fail("--simulation_time must be >= 0")

    if args.incubation_period <= 0.0:
        fail("--incubation_period must be > 0")
    if args.infectivity_period <= 0.0:
        fail("--infectivity_period must be > 0")

    if args.transmission_rate < 0.0:
        fail("--transmission_rate must be >= 0")


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    try:
        _validate_args(args)
    except ValueError as e:
        logging.error(str(e))
        return 2

    env = simpy.Environment(initial_time=0.0)

    sim = SEIRDSimulator(
        env,
        total_population=args.total_population,
        transmission_rate=args.transmission_rate,
        incubation_period=args.incubation_period,
        infectivity_period=args.infectivity_period,
        mortality_pct=args.mortality,
        dt=args.dt,
        simulation_time=args.simulation_time,
        initial_infective=args.initial_infective,
    )

    env.process(sim.run())
    env.run(until=args.simulation_time + 1e-12)

    st = sim.state

    # Output JSONL final state only (stdout).
    out = {
        "time": float(round(float(args.simulation_time), 2)),
        "susceptible": float(round(st.s, 2)),
        "exposed": float(round(st.e, 2)),
        "infective": float(round(st.i, 2)),
        "recovered": float(round(st.r, 2)),
        "deceased": float(round(st.d, 2)),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
