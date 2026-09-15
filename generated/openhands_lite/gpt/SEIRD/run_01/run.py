#!/usr/bin/env python3
import argparse
import json
import logging
import sys

import simpy


logger = logging.getLogger(__name__)


def _nonneg_int(value: str) -> int:
    try:
        iv = int(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Expected int, got: {value!r}") from e
    if iv < 0:
        raise argparse.ArgumentTypeError(f"Expected int >= 0, got: {iv}")
    return iv


def _pos_float(value: str) -> float:
    try:
        fv = float(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Expected float, got: {value!r}") from e
    if fv <= 0:
        raise argparse.ArgumentTypeError(f"Expected float > 0, got: {fv}")
    return fv


def _nonneg_float(value: str) -> float:
    try:
        fv = float(value)
    except ValueError as e:
        raise argparse.ArgumentTypeError(f"Expected float, got: {value!r}") from e
    if fv < 0:
        raise argparse.ArgumentTypeError(f"Expected float >= 0, got: {fv}")
    return fv


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="SEIRD discrete-time simulation (DES via SimPy)")

    p.add_argument("--test_name", type=str, required=True)
    p.add_argument("--mortality", type=_nonneg_float, default=10.0)
    p.add_argument("--infectivity_period", type=_pos_float, default=14.0)
    p.add_argument("--dt", type=_pos_float, default=0.1)
    p.add_argument("--incubation_period", type=_pos_float, default=5.0)
    p.add_argument("--total_population", type=_nonneg_int, default=1000)
    p.add_argument("--initial_infective", type=_nonneg_int, default=10)
    p.add_argument("--transmission_rate", type=_nonneg_float, default=2.5)
    p.add_argument("--simulation_time", type=_nonneg_float, default=10.0)

    args = p.parse_args(argv)

    if args.mortality > 100.0:
        p.error("--mortality must be in [0, 100]")
    if args.initial_infective > args.total_population:
        p.error("--initial_infective must be <= --total_population")

    return args


def seird_step(*, s: float, e: float, i: float, r: float, d: float, n: float,
              beta: float, incubation_period: float, infectivity_period: float,
              mortality_pct: float, dt: float) -> tuple[float, float, float, float, float]:
    new_exposed = (beta * s * i / n) * dt if n > 0 else 0.0
    new_exposed = min(new_exposed, s)

    new_infective = (e / incubation_period) * dt
    new_infective = min(new_infective, e)

    mort = mortality_pct / 100.0
    new_deceased = (i / infectivity_period) * mort * dt
    new_recovered = (i / infectivity_period) * (1.0 - mort) * dt

    s2 = s - new_exposed
    e2 = e + new_exposed - new_infective
    i2 = i + new_infective - new_deceased - new_recovered
    r2 = r + new_recovered
    d2 = d + new_deceased

    return s2, e2, i2, r2, d2


def simulate(env: simpy.Environment, *, args: argparse.Namespace, state: dict) -> simpy.events.Event:
    n = float(args.total_population)

    while env.now + 1e-12 < args.simulation_time:
        step = min(args.dt, args.simulation_time - env.now)

        s, e, i, r, d = state["s"], state["e"], state["i"], state["r"], state["d"]
        s2, e2, i2, r2, d2 = seird_step(
            s=s,
            e=e,
            i=i,
            r=r,
            d=d,
            n=n,
            beta=float(args.transmission_rate),
            incubation_period=float(args.incubation_period),
            infectivity_period=float(args.infectivity_period),
            mortality_pct=float(args.mortality),
            dt=float(step),
        )

        state.update({"s": s2, "e": e2, "i": i2, "r": r2, "d": d2})

        total = state["s"] + state["e"] + state["i"] + state["r"] + state["d"]
        if n > 0 and abs(total - n) > 1e-6:
            logger.debug("population drift at t=%.6f: total=%.9f n=%.9f", env.now, total, n)

        yield env.timeout(step)


def main(argv: list[str]) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s: %(message)s")
    args = parse_args(argv)

    s0 = float(args.total_population - args.initial_infective)
    e0 = 0.0
    i0 = float(args.initial_infective)
    r0 = 0.0
    d0 = 0.0

    state = {"s": s0, "e": e0, "i": i0, "r": r0, "d": d0}

    env = simpy.Environment(initial_time=0.0)
    env.process(simulate(env, args=args, state=state))
    env.run(until=float(args.simulation_time) + 1e-12)

    out = {
        "time": round(float(env.now), 2),
        "susceptible": round(float(state["s"]), 2),
        "exposed": round(float(state["e"]), 2),
        "infective": round(float(state["i"]), 2),
        "recovered": round(float(state["r"]), 2),
        "deceased": round(float(state["d"]), 2),
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
