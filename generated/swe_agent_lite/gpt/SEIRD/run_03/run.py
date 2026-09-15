#!/usr/bin/env python3
"""SEIRD epidemic compartmental model simulated with Discrete Event Simulation (SimPy).

Outputs ONLY JSONL objects to stdout. All logs go to stderr.
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
    p = argparse.ArgumentParser(description="SEIRD DES simulation (discrete-time updates using SimPy)")
    p.add_argument("--test_name", type=str, required=True, help="Name of the test case being run")

    p.add_argument("--mortality", type=float, default=10.0, help="Mortality rate as percentage (0-100)")
    p.add_argument("--infectivity_period", type=float, default=14.0, help="Average days a person stays infectious")
    p.add_argument("--dt", type=float, default=0.1, help="Time step for numerical integration in days")
    p.add_argument("--incubation_period", type=float, default=5.0, help="Average days from exposure to becoming infectious")
    p.add_argument("--total_population", type=int, default=1000, help="Total population size (integer >= 0)")
    p.add_argument("--initial_infective", type=int, default=10, help="Initial number of infected individuals")
    p.add_argument("--transmission_rate", type=float, default=2.5, help="Transmission rate (beta) per day")
    p.add_argument("--simulation_time", type=float, default=10.0, help="Total simulation time in days")

    return p


def validate_args(args: argparse.Namespace) -> None:
    if args.total_population < 0:
        raise ValueError("--total_population must be >= 0")
    if args.initial_infective < 0:
        raise ValueError("--initial_infective must be >= 0")
    if args.initial_infective > args.total_population:
        raise ValueError("--initial_infective cannot exceed --total_population")
    if args.dt <= 0:
        raise ValueError("--dt must be > 0")
    if args.simulation_time < 0:
        raise ValueError("--simulation_time must be >= 0")
    if args.infectivity_period <= 0:
        raise ValueError("--infectivity_period must be > 0")
    if args.incubation_period <= 0:
        raise ValueError("--incubation_period must be > 0")
    if not (0.0 <= args.mortality <= 100.0):
        raise ValueError("--mortality must be between 0 and 100")


def seird_step(state: SEIRDState, *, beta: float, N: float, incubation_period: float,
              infectivity_period: float, mortality_pct: float, dt: float) -> SEIRDState:
    """One Euler step according to the specification, with cutting to avoid negatives."""

    S_old, E_old, I_old, R_old, D_old = (
        state.susceptible,
        state.exposed,
        state.infective,
        state.recovered,
        state.deceased,
    )

    # S -> E
    new_exposed = (beta * S_old * I_old / N) * dt if N > 0 else 0.0
    if new_exposed > S_old:
        new_exposed = S_old

    # E -> I
    new_infective = (E_old / incubation_period) * dt
    if new_infective > E_old:
        new_infective = E_old

    # I -> R / D
    mort = mortality_pct / 100.0
    new_deceased = (I_old / infectivity_period) * mort * dt
    new_recovered = (I_old / infectivity_period) * (1.0 - mort) * dt

    # Cut to avoid removing more than available due to numerical issues
    total_out = new_deceased + new_recovered
    if total_out > I_old:
        if total_out > 0:
            scale = I_old / total_out
            new_deceased *= scale
            new_recovered *= scale
        else:
            new_deceased = 0.0
            new_recovered = 0.0

    S_new = S_old - new_exposed
    E_new = E_old + new_exposed - new_infective
    I_new = I_old + new_infective - new_deceased - new_recovered
    R_new = R_old + new_recovered
    D_new = D_old + new_deceased

    # Guard against tiny negative values from floating point
    def nz(x: float) -> float:
        return 0.0 if x < 0 and abs(x) < 1e-12 else x

    return SEIRDState(nz(S_new), nz(E_new), nz(I_new), nz(R_new), nz(D_new))


def simulation_process(env: simpy.Environment, state_box: dict, params: dict) -> simpy.events.Event:
    """SimPy process that advances the SEIRD state every dt until simulation_time."""

    dt = params["dt"]
    sim_time = params["simulation_time"]

    # Run discrete-time updates at fixed intervals.
    while env.now + 1e-12 < sim_time:
        yield env.timeout(dt)
        state_box["state"] = seird_step(state_box["state"], **params)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        validate_args(args)
    except Exception as e:
        logging.error(str(e))
        return 2

    N = float(args.total_population)
    initial_I = float(args.initial_infective)

    state = SEIRDState(
        susceptible=N - initial_I,
        exposed=0.0,
        infective=initial_I,
        recovered=0.0,
        deceased=0.0,
    )

    env = simpy.Environment(initial_time=0.0)

    params = {
        "beta": float(args.transmission_rate),
        "N": N,
        "incubation_period": float(args.incubation_period),
        "infectivity_period": float(args.infectivity_period),
        "mortality_pct": float(args.mortality),
        "dt": float(args.dt),
        "simulation_time": float(args.simulation_time),
    }

    state_box = {"state": state}
    env.process(simulation_process(env, state_box, params))

    # Run until the requested absolute time.
    env.run(until=float(args.simulation_time))

    final_state: SEIRDState = state_box["state"]

    out = {
        "time": float(f"{float(args.simulation_time):.2f}"),
        "susceptible": float(f"{final_state.susceptible:.2f}"),
        "exposed": float(f"{final_state.exposed:.2f}"),
        "infective": float(f"{final_state.infective:.2f}"),
        "recovered": float(f"{final_state.recovered:.2f}"),
        "deceased": float(f"{final_state.deceased:.2f}"),
    }

    # stdout must contain ONLY JSONL objects.
    sys.stdout.write(json.dumps(out) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
