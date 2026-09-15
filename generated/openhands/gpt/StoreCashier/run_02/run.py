#!/usr/bin/env python3
import argparse
import json
import random
from dataclasses import dataclass
from typing import Optional

import simpy


def parse_hhmmssmmm(value: str) -> int:
    parts = value.split(":")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "simulation_time must be in HH:MM:SS:mmm format"
        )
    try:
        hh, mm, ss, mmm = (int(p) for p in parts)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            "simulation_time must be in HH:MM:SS:mmm format"
        ) from e

    if hh < 0 or mm < 0 or ss < 0 or mmm < 0 or mm >= 60 or ss >= 60 or mmm >= 1000:
        raise argparse.ArgumentTypeError(
            "simulation_time must be in HH:MM:SS:mmm format"
        )

    return (((hh * 60 + mm) * 60 + ss) * 1000) + mmm


def format_hhmmssmmm(ms: int) -> str:
    if ms < 0:
        ms = 0
    total_seconds, mmm = divmod(ms, 1000)
    total_minutes, ss = divmod(total_seconds, 60)
    hh, mm = divmod(total_minutes, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{mmm:03d}"


def ms_to_seconds(ms: int) -> float:
    return ms / 1000.0


def clamp(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def sample_clamped_ms(
    rng: random.Random,
    mean_s: float,
    std_s: float,
    low_s: float,
    high_s: float,
) -> int:
    if std_s == 0.0:
        v = mean_s
    else:
        v = rng.gauss(mean_s, std_s)
        v = clamp(v, low_s, high_s)
    return int(round(v * 1000.0))


class JsonlLogger:
    def __init__(self, horizon_ms: int):
        self.horizon_ms = horizon_ms

    def emit(self, time_ms: int, event: str, entity_type: str, entity: str, payload: dict) -> None:
        if time_ms > self.horizon_ms:
            return
        obj = {
            "time": ms_to_seconds(time_ms),
            "time_str": format_hhmmssmmm(time_ms),
            "event": event,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload,
        }
        print(json.dumps(obj, separators=(",", ":"), sort_keys=False), flush=True)


@dataclass(frozen=True)
class Client:
    client_id: int
    arrival_time_ms: int


def client_generator(
    env: simpy.Environment,
    store: simpy.Store,
    logger: JsonlLogger,
    horizon_ms: int,
    rng: random.Random,
    client_mean: float,
    client_stddev: float,
):
    next_id = 1

    # First client at t = 0.0
    client = Client(client_id=next_id, arrival_time_ms=int(env.now))
    logger.emit(
        int(env.now),
        "client_generated",
        "client_generator",
        "ClientGenerator",
        {
            "client_id": client.client_id,
            "arrival_time": ms_to_seconds(client.arrival_time_ms),
        },
    )
    store.put(client)
    next_id += 1

    max_interval = client_mean + 5.0 * client_stddev
    while True:
        interval_ms = sample_clamped_ms(rng, client_mean, client_stddev, 0.0, max_interval)
        yield env.timeout(interval_ms)

        if int(env.now) > horizon_ms:
            return

        client = Client(client_id=next_id, arrival_time_ms=int(env.now))
        logger.emit(
            int(env.now),
            "client_generated",
            "client_generator",
            "ClientGenerator",
            {
                "client_id": client.client_id,
                "arrival_time": ms_to_seconds(client.arrival_time_ms),
            },
        )
        store.put(client)
        next_id += 1


def employee_process(
    env: simpy.Environment,
    store: simpy.Store,
    logger: JsonlLogger,
    horizon_ms: int,
    rng: random.Random,
    employee_id: int,
    mean_s: float,
    std_s: float,
):
    employee_entity = f"Employee_{employee_id}"

    logger.emit(
        int(env.now),
        "employee_available",
        "employee",
        employee_entity,
        {"employee_id": employee_id},
    )

    low = mean_s - 3.0 * std_s
    high = mean_s + 3.0 * std_s

    while True:
        client: Client = yield store.get()
        paired_time_ms = int(env.now)

        logger.emit(
            paired_time_ms,
            "client_paired",
            "queue",
            "Queue",
            {
                "client_id": client.client_id,
                "employee_id": employee_id,
                "paired_time": ms_to_seconds(paired_time_ms),
            },
        )

        service_ms = sample_clamped_ms(rng, mean_s, std_s, low, high)
        yield env.timeout(service_ms)

        dispatched_ms = int(env.now)
        delay_ms = dispatched_ms - client.arrival_time_ms
        logger.emit(
            dispatched_ms,
            "client_served",
            "employee",
            employee_entity,
            {
                "client_id": client.client_id,
                "employee_id": employee_id,
                "arrived": ms_to_seconds(client.arrival_time_ms),
                "dispatched": ms_to_seconds(dispatched_ms),
                "delay": ms_to_seconds(delay_ms),
            },
        )

        logger.emit(
            dispatched_ms,
            "employee_available",
            "employee",
            employee_entity,
            {"employee_id": employee_id},
        )

        if dispatched_ms >= horizon_ms:
            return


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Two-employee store cashier DES simulation")
    p.add_argument(
        "--simulation_time",
        type=str,
        default="00:05:00:000",
        help='Simulation horizon in HH:MM:SS:mmm (default "00:05:00:000")',
    )
    p.add_argument("--client_mean", type=float, default=10.0)
    p.add_argument("--client_stddev", type=float, default=5.0)
    p.add_argument("--employee_1_mean", type=float, default=20.0)
    p.add_argument("--employee_1_stddev", type=float, default=0.0)
    p.add_argument("--employee_2_mean", type=float, default=30.0)
    p.add_argument("--employee_2_stddev", type=float, default=4.0)
    p.add_argument("--seed", type=int, default=None)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    horizon_ms = parse_hhmmssmmm(args.simulation_time)

    rng = random.Random(args.seed)

    env = simpy.Environment(initial_time=0)
    store: simpy.Store = simpy.Store(env)
    logger = JsonlLogger(horizon_ms=horizon_ms)

    env.process(
        employee_process(
            env,
            store,
            logger,
            horizon_ms,
            rng,
            employee_id=1,
            mean_s=args.employee_1_mean,
            std_s=args.employee_1_stddev,
        )
    )
    env.process(
        employee_process(
            env,
            store,
            logger,
            horizon_ms,
            rng,
            employee_id=2,
            mean_s=args.employee_2_mean,
            std_s=args.employee_2_stddev,
        )
    )
    env.process(
        client_generator(
            env,
            store,
            logger,
            horizon_ms,
            rng,
            client_mean=args.client_mean,
            client_stddev=args.client_stddev,
        )
    )

    # SimPy stops when env.now >= until, and does not necessarily
    # execute events scheduled exactly at `until` when `until` is a number.
    # Run one extra millisecond and filter emissions beyond horizon.
    env.run(until=horizon_ms + 1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
