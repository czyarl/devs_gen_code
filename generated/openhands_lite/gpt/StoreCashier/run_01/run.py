import argparse
import json
import random
from dataclasses import dataclass
from typing import Optional

import simpy
from simpy.core import EmptySchedule


def _quantize_seconds(x: float) -> float:
    return round(float(x) + 1e-12, 3)


def parse_hhmmssmmm(s: str) -> float:
    parts = s.strip().split(":")
    if len(parts) != 4:
        raise ValueError("simulation_time must be HH:MM:SS:mmm")
    hh, mm, ss, mmm = (int(p) for p in parts)
    if hh < 0 or mm < 0 or ss < 0 or mmm < 0:
        raise ValueError("simulation_time components must be non-negative")
    if mm >= 60 or ss >= 60 or mmm >= 1000:
        raise ValueError("simulation_time must be HH:MM:SS:mmm with valid ranges")
    return hh * 3600 + mm * 60 + ss + mmm / 1000.0


def format_hhmmssmmm(seconds: float) -> str:
    total_ms = int(round(_quantize_seconds(seconds) * 1000))
    hh = total_ms // (3600 * 1000)
    total_ms %= 3600 * 1000
    mm = total_ms // (60 * 1000)
    total_ms %= 60 * 1000
    ss = total_ms // 1000
    mmm = total_ms % 1000
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{mmm:03d}"


class EventLogger:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def emit(self, event: str, entity_type: str, entity: str, payload: dict) -> None:
        t = _quantize_seconds(self.env.now)
        obj = {
            "time": t,
            "time_str": format_hhmmssmmm(t),
            "event": event,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload,
        }
        print(json.dumps(obj, separators=(",", ":")))


def _clamp(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def sample_trunc_normal(
    rng: random.Random,
    mean: float,
    stddev: float,
    lo: float,
    hi: float,
) -> float:
    if stddev == 0.0:
        return _quantize_seconds(_clamp(mean, lo, hi))
    x = rng.gauss(mean, stddev)
    x = _clamp(x, lo, hi)
    return _quantize_seconds(x)


@dataclass
class Client:
    client_id: int
    arrival_time: float
    paired_time: Optional[float] = None
    employee_id: Optional[int] = None


def client_generator(
    env: simpy.Environment,
    logger: EventLogger,
    queue: simpy.Store,
    horizon_s: float,
    rng: random.Random,
    client_mean: float,
    client_stddev: float,
):
    client_id = 1
    while True:
        now = _quantize_seconds(env.now)
        logger.emit(
            "client_generated",
            "client_generator",
            "ClientGenerator",
            {"client_id": client_id, "arrival_time": now},
        )
        yield queue.put(Client(client_id=client_id, arrival_time=now))

        interval_hi = client_mean + 5 * client_stddev
        interval = sample_trunc_normal(rng, client_mean, client_stddev, 0.0, interval_hi)

        next_t = _quantize_seconds(env.now + interval)
        if next_t > horizon_s:
            return

        yield env.timeout(interval)
        client_id += 1


def employee_process(
    env: simpy.Environment,
    logger: EventLogger,
    queue: simpy.Store,
    rng: random.Random,
    employee_id: int,
    service_mean: float,
    service_stddev: float,
):
    employee_name = f"Employee_{employee_id}"

    service_lo = max(0.0, service_mean - 3 * service_stddev)
    service_hi = service_mean + 3 * service_stddev

    while True:
        logger.emit(
            "employee_available",
            "employee",
            employee_name,
            {"employee_id": employee_id},
        )

        client: Client = yield queue.get()

        paired_time = _quantize_seconds(env.now)
        client.paired_time = paired_time
        client.employee_id = employee_id
        logger.emit(
            "client_paired",
            "queue",
            "Queue",
            {"client_id": client.client_id, "employee_id": employee_id, "paired_time": paired_time},
        )

        duration = sample_trunc_normal(rng, service_mean, service_stddev, service_lo, service_hi)
        yield env.timeout(duration)

        dispatched = _quantize_seconds(env.now)
        arrived = client.arrival_time
        delay = _quantize_seconds(dispatched - arrived)
        logger.emit(
            "client_served",
            "employee",
            employee_name,
            {
                "client_id": client.client_id,
                "employee_id": employee_id,
                "arrived": arrived,
                "dispatched": dispatched,
                "delay": delay,
            },
        )


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Two-employee store cashier DES simulation")
    p.add_argument("--simulation_time", type=str, default="00:05:00:000")

    p.add_argument("--client_mean", type=float, default=10.0)
    p.add_argument("--client_stddev", type=float, default=5.0)

    p.add_argument("--employee_1_mean", type=float, default=20.0)
    p.add_argument("--employee_1_stddev", type=float, default=0.0)

    p.add_argument("--employee_2_mean", type=float, default=30.0)
    p.add_argument("--employee_2_stddev", type=float, default=4.0)

    p.add_argument("--seed", type=int, default=None)
    return p


def run_until(env: simpy.Environment, horizon_s: float) -> None:
    while True:
        try:
            if env.peek() > horizon_s + 1e-12:
                return
            env.step()
        except EmptySchedule:
            return


def main() -> None:
    args = build_arg_parser().parse_args()

    horizon_s = _quantize_seconds(parse_hhmmssmmm(args.simulation_time))
    if horizon_s < 0.0:
        raise SystemExit("simulation_time must be non-negative")

    if args.client_stddev < 0.0:
        raise SystemExit("client_stddev must be non-negative")
    if args.employee_1_stddev < 0.0 or args.employee_2_stddev < 0.0:
        raise SystemExit("employee stddev values must be non-negative")

    rng = random.Random(args.seed)

    env = simpy.Environment()
    logger = EventLogger(env)
    queue = simpy.Store(env)

    env.process(
        employee_process(
            env,
            logger,
            queue,
            rng,
            employee_id=1,
            service_mean=args.employee_1_mean,
            service_stddev=args.employee_1_stddev,
        )
    )
    env.process(
        employee_process(
            env,
            logger,
            queue,
            rng,
            employee_id=2,
            service_mean=args.employee_2_mean,
            service_stddev=args.employee_2_stddev,
        )
    )
    env.process(
        client_generator(
            env,
            logger,
            queue,
            horizon_s,
            rng,
            client_mean=args.client_mean,
            client_stddev=args.client_stddev,
        )
    )

    run_until(env, horizon_s)


if __name__ == "__main__":
    main()
