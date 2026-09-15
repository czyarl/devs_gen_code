#!/usr/bin/env python3
import argparse
import json
import logging
import sys
from collections import namedtuple

import simpy


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SEIRD discrete-time simulation using SimPy (DES).")
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


def _validate_args(args: argparse.Namespace) -> None:
    if args.total_population < 0:
        raise ValueError("--total_population must be >= 0")
    if args.initial_infective < 0:
        raise ValueError("--initial_infective must be >= 0")
    if args.initial_infective > args.total_population:
        raise ValueError("--initial_infective must be <= --total_population")

    if args.dt <= 0:
        raise ValueError("--dt must be > 0")
    if args.simulation_time < 0:
        raise ValueError("--simulation_time must be >= 0")

    if args.incubation_period <= 0:
        raise ValueError("--incubation_period must be > 0")
    if args.infectivity_period <= 0:
        raise ValueError("--infectivity_period must be > 0")

    if args.transmission_rate < 0:
        raise ValueError("--transmission_rate must be >= 0")

    if not (0.0 <= args.mortality <= 100.0):
        raise ValueError("--mortality must be between 0 and 100")


def _clamp_nonnegative(x: float) -> float:
    return 0.0 if x < 0.0 and abs(x) < 1e-12 else x


SEIRDState = namedtuple("SEIRDState", ["susceptible", "exposed", "infective", "recovered", "deceased"])


class SEIRDModel:
    def __init__(
        self,
        *,
        total_population: int,
        initial_infective: int,
        transmission_rate: float,
        incubation_period: float,
        infectivity_period: float,
        mortality_pct: float,
    ) -> None:
        self.N = float(total_population)
        self.beta = float(transmission_rate)
        self.incubation_period = float(incubation_period)
        self.infectivity_period = float(infectivity_period)
        self.mortality_frac = float(mortality_pct) / 100.0

        i0 = float(initial_infective)
        self.state = SEIRDState(
            susceptible=self.N - i0,
            exposed=0.0,
            infective=i0,
            recovered=0.0,
            deceased=0.0,
        )

    def step(self, dt: float) -> None:
        s0 = self.state.susceptible
        e0 = self.state.exposed
        i0 = self.state.infective
        r0 = self.state.recovered
        d0 = self.state.deceased

        if self.N > 0.0 and s0 > 0.0 and i0 > 0.0 and self.beta > 0.0:
            new_exposed = (self.beta * s0 * i0 / self.N) * dt
            new_exposed = min(new_exposed, s0)
        else:
            new_exposed = 0.0

        if e0 > 0.0:
            new_infective = (e0 / self.incubation_period) * dt
            new_infective = min(new_infective, e0)
        else:
            new_infective = 0.0

        if i0 > 0.0:
            total_exit = (i0 / self.infectivity_period) * dt
            total_exit = min(total_exit, i0)
            new_deceased = total_exit * self.mortality_frac
            new_recovered = total_exit * (1.0 - self.mortality_frac)
        else:
            new_deceased = 0.0
            new_recovered = 0.0

        s1 = s0 - new_exposed
        e1 = e0 + new_exposed - new_infective
        i1 = i0 + new_infective - new_deceased - new_recovered
        r1 = r0 + new_recovered
        d1 = d0 + new_deceased

        self.state = SEIRDState(
            susceptible=_clamp_nonnegative(s1),
            exposed=_clamp_nonnegative(e1),
            infective=_clamp_nonnegative(i1),
            recovered=_clamp_nonnegative(r1),
            deceased=_clamp_nonnegative(d1),
        )

    def final_output(self, time: float) -> dict:
        st = self.state
        return {
            "time": round(float(time), 2),
            "susceptible": round(float(st.susceptible), 2),
            "exposed": round(float(st.exposed), 2),
            "infective": round(float(st.infective), 2),
            "recovered": round(float(st.recovered), 2),
            "deceased": round(float(st.deceased), 2),
        }


def seird_process(env: simpy.Environment, model: SEIRDModel, dt: float, t_end: float):
    while env.now < t_end - 1e-12:
        step = dt
        remaining = t_end - env.now
        if remaining < step:
            step = remaining

        model.step(step)
        yield env.timeout(step)


def main() -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="[%(levelname)s] %(message)s")

    parser = _build_arg_parser()
    args = parser.parse_args()

    try:
        _validate_args(args)
    except ValueError as e:
        logging.error(str(e))
        return 2

    logging.info(
        "Running %s: N=%d I0=%d beta=%.6g dt=%.6g T=%.6g",
        args.test_name,
        args.total_population,
        args.initial_infective,
        args.transmission_rate,
        args.dt,
        args.simulation_time,
    )

    model = SEIRDModel(
        total_population=args.total_population,
        initial_infective=args.initial_infective,
        transmission_rate=args.transmission_rate,
        incubation_period=args.incubation_period,
        infectivity_period=args.infectivity_period,
        mortality_pct=args.mortality,
    )

    env = simpy.Environment(initial_time=0.0)
    env.process(seird_process(env, model, float(args.dt), float(args.simulation_time)))
    env.run(until=float(args.simulation_time))

    print(json.dumps(model.final_output(env.now)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
