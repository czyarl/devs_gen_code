#!/usr/bin/env python3
"""SEIRD discrete-time simulation using a DES engine (SimPy).

Requirements implemented:
- Python 3.10+
- argparse-based CLI
- No stdin required
- stdout emits ONLY JSONL (final state)
- stderr used for logs

Model:
S -> E -> I -> (R or D)
with flows computed from the previous step state and applied every dt.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

import simpy


LOG = logging.getLogger("seird")


class SEIRDState:
    __slots__ = ("susceptible", "exposed", "infective", "recovered", "deceased")

    def __init__(self, susceptible: float, exposed: float, infective: float, recovered: float, deceased: float):
        self.susceptible = float(susceptible)
        self.exposed = float(exposed)
        self.infective = float(infective)
        self.recovered = float(recovered)
        self.deceased = float(deceased)

    def total(self) -> float:
        return self.susceptible + self.exposed + self.infective + self.recovered + self.deceased


def _as_2dp_float(x: float) -> float:
    # Ensure we output JSON numbers as floats with at least 2 decimals.
    return float(f"{x:.2f}")


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SEIRD epidemic compartment model (discrete-time, SimPy).")
    p.add_argument("--test_name", type=str, required=True, help="Name of the test case being run.")

    p.add_argument("--mortality", type=float, default=10.0, help="Mortality rate (percentage 0-100).")
    p.add_argument("--infectivity_period", type=float, default=14.0, help="Average days a person stays infectious.")
    p.add_argument("--dt", type=float, default=0.1, help="Time step in days.")
    p.add_argument("--incubation_period", type=float, default=5.0, help="Average days from exposure to infectious.")
    p.add_argument("--total_population", type=int, default=1000, help="Total population (integer >= 0).")
    p.add_argument("--initial_infective", type=int, default=10, help="Initial number of infective individuals.")
    p.add_argument("--transmission_rate", type=float, default=2.5, help="Transmission rate beta per day.")
    p.add_argument("--simulation_time", type=float, default=10.0, help="Total simulation time in days.")

    return p


def validate_args(args: argparse.Namespace) -> None:
    if args.total_population < 0:
        raise ValueError("--total_population must be >= 0")
    if args.initial_infective < 0:
        raise ValueError("--initial_infective must be >= 0")
    if args.initial_infective > args.total_population:
        raise ValueError("--initial_infective must be <= --total_population")

    if not (0.0 <= args.mortality <= 100.0):
        raise ValueError("--mortality must be between 0 and 100")

    if args.infectivity_period <= 0.0:
        raise ValueError("--infectivity_period must be > 0")
    if args.incubation_period <= 0.0:
        raise ValueError("--incubation_period must be > 0")
    if args.dt <= 0.0:
        raise ValueError("--dt must be > 0")
    if args.simulation_time < 0.0:
        raise ValueError("--simulation_time must be >= 0")
    if args.transmission_rate < 0.0:
        raise ValueError("--transmission_rate must be >= 0")


def seird_process(env: simpy.Environment, args: argparse.Namespace, state: SEIRDState):
    """SimPy process advancing the SEIRD state in fixed time increments."""

    # Closed population N is constant.
    N = float(args.total_population)
    beta = float(args.transmission_rate)
    incubation_period = float(args.incubation_period)
    infectivity_period = float(args.infectivity_period)
    mortality_frac = float(args.mortality) / 100.0

    while env.now + 1e-12 < float(args.simulation_time):
        dt_step = min(float(args.dt), float(args.simulation_time) - float(env.now))

        S_old = state.susceptible
        E_old = state.exposed
        I_old = state.infective
        R_old = state.recovered
        D_old = state.deceased

        # S -> E
        if N > 0.0:
            new_exposed = (beta * S_old * I_old / N) * dt_step
        else:
            new_exposed = 0.0
        if new_exposed > S_old:
            new_exposed = S_old

        # E -> I
        new_infective = (E_old / incubation_period) * dt_step
        if new_infective > E_old:
            new_infective = E_old

        # I -> (R or D)
        out_of_I = (I_old / infectivity_period) * dt_step
        if out_of_I > I_old:
            # Not specified in the statement, but prevents negative compartments if dt is huge.
            LOG.warning("Capping I outflow to avoid negative infective (dt too large).")
            out_of_I = I_old
        new_deceased = out_of_I * mortality_frac
        new_recovered = out_of_I * (1.0 - mortality_frac)

        # Apply updates
        S_new = S_old - new_exposed
        E_new = E_old + new_exposed - new_infective
        I_new = I_old + new_infective - new_deceased - new_recovered
        R_new = R_old + new_recovered
        D_new = D_old + new_deceased

        # Numerical hygiene: avoid tiny negatives due to FP.
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

        state.susceptible = S_new
        state.exposed = E_new
        state.infective = I_new
        state.recovered = R_new
        state.deceased = D_new

        yield env.timeout(dt_step)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        validate_args(args)
    except Exception as e:
        LOG.error(str(e))
        return 2

    # Initial state
    N = float(args.total_population)
    I0 = float(args.initial_infective)
    state = SEIRDState(
        susceptible=N - I0,
        exposed=0.0,
        infective=I0,
        recovered=0.0,
        deceased=0.0,
    )

    env = simpy.Environment(initial_time=0.0)
    env.process(seird_process(env, args, state))

    # Run the DES until the requested absolute simulation time.
    # SimPy requires `until` to be strictly greater than current time.
    if float(args.simulation_time) > 0.0:
        env.run(until=float(args.simulation_time))

    # Output final state as JSONL only.
    out = {
        "time": _as_2dp_float(float(args.simulation_time)),
        "susceptible": _as_2dp_float(state.susceptible),
        "exposed": _as_2dp_float(state.exposed),
        "infective": _as_2dp_float(state.infective),
        "recovered": _as_2dp_float(state.recovered),
        "deceased": _as_2dp_float(state.deceased),
    }
    sys.stdout.write(json.dumps(out) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
