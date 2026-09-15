#!/usr/bin/env python3
import argparse
import json
import logging
import sys

import simpy


class SEIRDModel:
    def __init__(
        self,
        *,
        total_population: int,
        initial_infective: int,
        transmission_rate: float,
        incubation_period: float,
        infectivity_period: float,
        mortality: float,
    ):
        self.N = float(total_population)
        self.beta = float(transmission_rate)
        self.incubation_period = float(incubation_period)
        self.infectivity_period = float(infectivity_period)
        self.mortality = float(mortality) / 100.0

        i0 = float(initial_infective)
        self.susceptible = float(total_population) - i0
        self.exposed = 0.0
        self.infective = i0
        self.recovered = 0.0
        self.deceased = 0.0

    def step(self, dt: float) -> None:
        s_old = self.susceptible
        e_old = self.exposed
        i_old = self.infective

        if self.N <= 0.0 or dt <= 0.0:
            return

        new_exposed = (self.beta * s_old * i_old / self.N) * dt
        new_exposed = min(new_exposed, s_old)

        new_infective = (e_old / self.incubation_period) * dt
        new_infective = min(new_infective, e_old)

        new_deceased = (i_old / self.infectivity_period) * self.mortality * dt
        new_recovered = (i_old / self.infectivity_period) * (1.0 - self.mortality) * dt

        total_out = new_deceased + new_recovered
        if total_out > i_old:
            if total_out > 0:
                scale = i_old / total_out
                new_deceased *= scale
                new_recovered *= scale

        self.susceptible = s_old - new_exposed
        self.exposed = e_old + new_exposed - new_infective
        self.infective = i_old + new_infective - new_deceased - new_recovered
        self.recovered += new_recovered
        self.deceased += new_deceased

        for attr in ("susceptible", "exposed", "infective", "recovered", "deceased"):
            v = getattr(self, attr)
            if v < 0.0:
                setattr(self, attr, 0.0)

        total = self.susceptible + self.exposed + self.infective + self.recovered + self.deceased
        if total > 0:
            drift = self.N - total
            self.susceptible = max(0.0, self.susceptible + drift)

    def run(self, env: simpy.Environment, *, dt: float, until: float):
        eps = 1e-12
        while env.now + eps < until:
            dt_step = min(dt, until - env.now)
            self.step(dt_step)
            yield env.timeout(dt_step)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="SEIRD compartmental epidemic simulation (DES via SimPy)")
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


def _validate_args(args: argparse.Namespace) -> None:
    if not (0.0 <= args.mortality <= 100.0):
        raise ValueError("--mortality must be between 0 and 100")
    if args.total_population < 0:
        raise ValueError("--total_population must be >= 0")
    if args.initial_infective < 0:
        raise ValueError("--initial_infective must be >= 0")
    if args.initial_infective > args.total_population:
        raise ValueError("--initial_infective must be <= total_population")
    if args.transmission_rate < 0.0:
        raise ValueError("--transmission_rate must be >= 0")
    if args.dt <= 0.0:
        raise ValueError("--dt must be > 0")
    if args.simulation_time < 0.0:
        raise ValueError("--simulation_time must be >= 0")
    if args.incubation_period <= 0.0:
        raise ValueError("--incubation_period must be > 0")
    if args.infectivity_period <= 0.0:
        raise ValueError("--infectivity_period must be > 0")


def main(argv: list[str]) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(levelname)s: %(message)s")

    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        _validate_args(args)
    except ValueError as e:
        logging.error(str(e))
        return 2

    env = simpy.Environment()
    model = SEIRDModel(
        total_population=args.total_population,
        initial_infective=args.initial_infective,
        transmission_rate=args.transmission_rate,
        incubation_period=args.incubation_period,
        infectivity_period=args.infectivity_period,
        mortality=args.mortality,
    )

    env.process(model.run(env, dt=float(args.dt), until=float(args.simulation_time)))
    env.run(until=float(args.simulation_time))

    line = (
        "{" 
        f"\"time\": {float(args.simulation_time):.2f}, "
        f"\"susceptible\": {model.susceptible:.2f}, "
        f"\"exposed\": {model.exposed:.2f}, "
        f"\"infective\": {model.infective:.2f}, "
        f"\"recovered\": {model.recovered:.2f}, "
        f"\"deceased\": {model.deceased:.2f}"
        "}"
    )
    sys.stdout.write(line + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
