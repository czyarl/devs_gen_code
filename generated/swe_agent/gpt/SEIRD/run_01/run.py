#!/usr/bin/env python3
"""SEIRD discrete-event simulation (DES) using SimPy.

Requirements implemented:
- Python 3.10+
- CLI with argparse (no stdin needed)
- Output ONLY JSONL on stdout (final state)
- Any logs go to stderr
- Uses DES (SimPy) with fixed time-step updates
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
    susceptible: float
    exposed: float
    infective: float
    recovered: float
    deceased: float


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SEIRD epidemic compartmental model (DES)")
    parser.add_argument("--test_name", type=str, required=True, help="Name of the test case being run")
    parser.add_argument("--mortality", type=float, default=10.0, help="Mortality rate as percentage (0-100)")
    parser.add_argument(
        "--infectivity_period",
        type=float,
        default=14.0,
        help="Average days a person stays infectious",
    )
    parser.add_argument("--dt", type=float, default=0.1, help="Time step for numerical integration in days")
    parser.add_argument(
        "--incubation_period",
        type=float,
        default=5.0,
        help="Average days from exposure to becoming infectious",
    )
    parser.add_argument("--total_population", type=int, default=1000, help="Total population size (integer >= 0)")
    parser.add_argument("--initial_infective", type=int, default=10, help="Initial number of infected individuals")
    parser.add_argument("--transmission_rate", type=float, default=2.5, help="Transmission rate (β) per day")
    parser.add_argument("--simulation_time", type=float, default=10.0, help="Total simulation time in days")
    return parser


def validate_args(args: argparse.Namespace) -> None:
    def die(msg: str) -> None:
        raise SystemExit(msg)

    if args.total_population < 0:
        die("--total_population must be >= 0")
    if args.initial_infective < 0:
        die("--initial_infective must be >= 0")
    if args.initial_infective > args.total_population:
        die("--initial_infective must be <= --total_population")
    if not (0.0 <= args.mortality <= 100.0):
        die("--mortality must be in [0, 100]")
    if args.dt <= 0.0:
        die("--dt must be > 0")
    if args.simulation_time < 0.0:
        die("--simulation_time must be >= 0")
    if args.incubation_period <= 0.0:
        die("--incubation_period must be > 0")
    if args.infectivity_period <= 0.0:
        die("--infectivity_period must be > 0")
    if args.transmission_rate < 0.0:
        die("--transmission_rate must be >= 0")


class SEIRDSimulator:
    def __init__(
        self,
        *,
        env: simpy.Environment,
        transmission_rate: float,
        incubation_period: float,
        infectivity_period: float,
        mortality_pct: float,
        dt: float,
        total_population: int,
        initial_infective: int,
        simulation_time: float,
    ) -> None:
        self.env = env
        self.beta = float(transmission_rate)
        self.incubation_period = float(incubation_period)
        self.infectivity_period = float(infectivity_period)
        self.mortality = float(mortality_pct) / 100.0
        self.dt = float(dt)
        self.N = float(total_population)
        self.simulation_time = float(simulation_time)

        self.state = SEIRDState(
            susceptible=float(total_population - initial_infective),
            exposed=0.0,
            infective=float(initial_infective),
            recovered=0.0,
            deceased=0.0,
        )

    def step(self, dt: float) -> None:
        # Snapshot old state
        S_old = self.state.susceptible
        E_old = self.state.exposed
        I_old = self.state.infective
        R_old = self.state.recovered
        D_old = self.state.deceased

        # If N == 0, dynamics are zero (avoid division by zero).
        N = self.N if self.N > 0.0 else 1.0

        # S -> E
        new_exposed = (self.beta * S_old * I_old / N) * dt
        new_exposed = min(max(new_exposed, 0.0), S_old)

        # E -> I
        new_infective = (E_old / self.incubation_period) * dt
        new_infective = min(max(new_infective, 0.0), E_old)

        # I -> R and I -> D
        base_out = (I_old / self.infectivity_period) * dt
        new_deceased = base_out * self.mortality
        new_recovered = base_out * (1.0 - self.mortality)

        # Numerical safety: never move out more than I_old
        total_out = new_deceased + new_recovered
        if total_out > I_old and total_out > 0.0:
            scale = I_old / total_out
            new_deceased *= scale
            new_recovered *= scale

        # Update compartments
        S_new = S_old - new_exposed
        E_new = E_old + new_exposed - new_infective
        I_new = I_old + new_infective - new_deceased - new_recovered
        R_new = R_old + new_recovered
        D_new = D_old + new_deceased

        self.state = SEIRDState(
            susceptible=max(0.0, S_new),
            exposed=max(0.0, E_new),
            infective=max(0.0, I_new),
            recovered=max(0.0, R_new),
            deceased=max(0.0, D_new),
        )

    def run(self):
        t = 0.0
        while t < self.simulation_time - 1e-12:
            step_dt = min(self.dt, self.simulation_time - t)
            self.step(step_dt)
            t += step_dt
            yield self.env.timeout(step_dt)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    validate_args(args)

    env = simpy.Environment(initial_time=0.0)
    sim = SEIRDSimulator(
        env=env,
        transmission_rate=args.transmission_rate,
        incubation_period=args.incubation_period,
        infectivity_period=args.infectivity_period,
        mortality_pct=args.mortality,
        dt=args.dt,
        total_population=args.total_population,
        initial_infective=args.initial_infective,
        simulation_time=args.simulation_time,
    )

    # SimPy requires `until` to be strictly greater than current time.
    # For a zero-length simulation, we simply report the initial state.
    if args.simulation_time > 0.0:
        env.process(sim.run())
        env.run(until=args.simulation_time)

    # stdout: ONLY final JSONL
    out = {
        "time": float(f"{args.simulation_time:.2f}"),
        "susceptible": round(sim.state.susceptible, 2),
        "exposed": round(sim.state.exposed, 2),
        "infective": round(sim.state.infective, 2),
        "recovered": round(sim.state.recovered, 2),
        "deceased": round(sim.state.deceased, 2),
    }
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
