#!/usr/bin/env python3
import argparse
import json
import random
from dataclasses import dataclass
from typing import Optional

import simpy


def parse_hhmmssmmm(value: str) -> float:
    """Parse HH:MM:SS:mmm into seconds as a float."""
    parts = value.split(":")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "--simulation_time must be in HH:MM:SS:mmm format"
        )

    try:
        hh, mm, ss, mmm = (int(p) for p in parts)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            "--simulation_time must contain only integers"
        ) from e

    if hh < 0 or mm < 0 or ss < 0 or mmm < 0:
        raise argparse.ArgumentTypeError("--simulation_time cannot be negative")
    if mm >= 60 or ss >= 60 or mmm >= 1000:
        raise argparse.ArgumentTypeError("--simulation_time has out-of-range fields")

    return hh * 3600 + mm * 60 + ss + (mmm / 1000.0)


def format_hhmmssmmm(t: float) -> str:
    ms_total = int(round(t * 1000))
    if ms_total < 0:
        ms_total = 0

    hh = ms_total // 3_600_000
    ms_total -= hh * 3_600_000
    mm = ms_total // 60_000
    ms_total -= mm * 60_000
    ss = ms_total // 1_000
    ms = ms_total - ss * 1_000

    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ms:03d}"


def quantize_ms(x: float) -> float:
    return int(round(x * 1000.0)) / 1000.0


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def sample_truncated_normal_ms(
    rng: random.Random,
    mean: float,
    stddev: float,
    lo: float,
    hi: float,
) -> float:
    if stddev == 0.0:
        return quantize_ms(mean)

    x = rng.gauss(mean, stddev)
    x = clamp(x, lo, hi)
    x = quantize_ms(x)
    # Guard against rounding pushing outside bounds.
    x = clamp(x, lo, hi)
    return x


class EventLogger:
    def __init__(self, horizon: float):
        self.horizon = horizon

    def emit(
        self,
        t: float,
        event: str,
        entity_type: str,
        entity: str,
        payload: dict,
    ) -> None:
        if t > self.horizon:
            return

        tq = float(quantize_ms(t))
        obj = {
            "time": tq,
            "time_str": format_hhmmssmmm(tq),
            "event": event,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload,
        }
        print(json.dumps(obj, ensure_ascii=False))


@dataclass(frozen=True)
class Client:
    client_id: int
    arrival_time: float


@dataclass(frozen=True)
class EmployeeParams:
    employee_id: int
    mean: float
    stddev: float


def employee_process(
    env: simpy.Environment,
    horizon: float,
    logger: EventLogger,
    queue: simpy.Store,
    rng: random.Random,
    params: EmployeeParams,
):
    entity = f"Employee_{params.employee_id}"

    while True:
        now = env.now
        if now > horizon:
            return

        logger.emit(
            now,
            event="employee_available",
            entity_type="employee",
            entity=entity,
            payload={"employee_id": params.employee_id},
        )

        client: Client = yield queue.get()
        paired_time = env.now
        if paired_time > horizon:
            return

        logger.emit(
            paired_time,
            event="client_paired",
            entity_type="queue",
            entity="Queue",
            payload={
                "client_id": client.client_id,
                "employee_id": params.employee_id,
                "paired_time": float(quantize_ms(paired_time)),
            },
        )

        lo = max(0.0, params.mean - 3.0 * params.stddev)
        hi = params.mean + 3.0 * params.stddev
        service_duration = sample_truncated_normal_ms(
            rng, params.mean, params.stddev, lo=lo, hi=hi
        )

        yield env.timeout(service_duration)
        dispatched = env.now
        if dispatched > horizon:
            return

        arrived = client.arrival_time
        delay = dispatched - arrived

        logger.emit(
            dispatched,
            event="client_served",
            entity_type="employee",
            entity=entity,
            payload={
                "client_id": client.client_id,
                "employee_id": params.employee_id,
                "arrived": float(quantize_ms(arrived)),
                "dispatched": float(quantize_ms(dispatched)),
                "delay": float(quantize_ms(delay)),
            },
        )


def client_generator_process(
    env: simpy.Environment,
    horizon: float,
    logger: EventLogger,
    queue: simpy.Store,
    rng: random.Random,
    client_mean: float,
    client_stddev: float,
):
    client_id = 1

    while True:
        now = env.now
        if now > horizon:
            return

        logger.emit(
            now,
            event="client_generated",
            entity_type="client_generator",
            entity="ClientGenerator",
            payload={"client_id": client_id, "arrival_time": float(quantize_ms(now))},
        )
        yield queue.put(Client(client_id=client_id, arrival_time=now))

        client_id += 1

        lo = 0.0
        hi = client_mean + 5.0 * client_stddev
        interval = sample_truncated_normal_ms(
            rng, client_mean, client_stddev, lo=lo, hi=hi
        )

        next_time = env.now + interval
        if next_time > horizon:
            return
        yield env.timeout(interval)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Two-employee store cashier simulation")

    p.add_argument(
        "--simulation_time",
        type=str,
        default="00:05:00:000",
        help='Total simulation horizon in HH:MM:SS:mmm (default "00:05:00:000")',
    )

    p.add_argument("--client_mean", type=float, default=10.0)
    p.add_argument("--client_stddev", type=float, default=5.0)

    p.add_argument("--employee_1_mean", type=float, default=20.0)
    p.add_argument("--employee_1_stddev", type=float, default=0.0)

    p.add_argument("--employee_2_mean", type=float, default=30.0)
    p.add_argument("--employee_2_stddev", type=float, default=4.0)

    p.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Optional RNG seed for reproducibility (default: 0)",
    )

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    horizon = parse_hhmmssmmm(args.simulation_time)

    if args.client_stddev < 0:
        raise SystemExit("--client_stddev must be non-negative")
    if args.employee_1_stddev < 0 or args.employee_2_stddev < 0:
        raise SystemExit("--employee_1_stddev/--employee_2_stddev must be non-negative")
    if args.client_mean < 0 or args.employee_1_mean < 0 or args.employee_2_mean < 0:
        raise SystemExit("Means must be non-negative")

    rng = random.Random(args.seed)
    env = simpy.Environment()
    queue = simpy.Store(env)
    logger = EventLogger(horizon=horizon)

    env.process(
        employee_process(
            env,
            horizon,
            logger,
            queue,
            rng,
            EmployeeParams(
                employee_id=1, mean=args.employee_1_mean, stddev=args.employee_1_stddev
            ),
        )
    )
    env.process(
        employee_process(
            env,
            horizon,
            logger,
            queue,
            rng,
            EmployeeParams(
                employee_id=2, mean=args.employee_2_mean, stddev=args.employee_2_stddev
            ),
        )
    )
    env.process(
        client_generator_process(
            env,
            horizon,
            logger,
            queue,
            rng,
            client_mean=args.client_mean,
            client_stddev=args.client_stddev,
        )
    )

    run_until = horizon if horizon > 0.0 else 1e-9
    env.run(until=run_until)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
