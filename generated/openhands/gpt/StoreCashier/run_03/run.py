import argparse
import json
import random
from dataclasses import dataclass

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

    if hh < 0 or mm < 0 or ss < 0 or mmm < 0:
        raise argparse.ArgumentTypeError("simulation_time components must be non-negative")
    if mm >= 60 or ss >= 60 or mmm >= 1000:
        raise argparse.ArgumentTypeError("invalid time ranges for HH:MM:SS:mmm")

    return (((hh * 60 + mm) * 60) + ss) * 1000 + mmm


def ms_to_time_str(ms: int) -> str:
    if ms < 0:
        ms = 0
    total_seconds, mmm = divmod(ms, 1000)
    total_minutes, ss = divmod(total_seconds, 60)
    hh, mm = divmod(total_minutes, 60)
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{mmm:03d}"


def ms_to_seconds(ms: int) -> float:
    return round(ms / 1000.0, 3)


def sample_truncated_normal_seconds(
    rng: random.Random,
    mean: float,
    stddev: float,
    low: float,
    high: float,
) -> float:
    if stddev == 0.0:
        return float(mean)
    x = rng.gauss(mean, stddev)
    if x < low:
        return float(low)
    if x > high:
        return float(high)
    return float(x)


def sample_interval_ms(rng: random.Random, mean: float, stddev: float) -> int:
    high = mean + 5.0 * stddev
    interval_s = sample_truncated_normal_seconds(rng, mean, stddev, 0.0, high)
    return int(round(interval_s * 1000.0))


def sample_service_ms(rng: random.Random, mean: float, stddev: float) -> int:
    low = max(0.0, mean - 3.0 * stddev)
    high = mean + 3.0 * stddev
    duration_s = sample_truncated_normal_seconds(rng, mean, stddev, low, high)
    return int(round(duration_s * 1000.0))


@dataclass
class Client:
    client_id: int
    arrived_ms: int
    paired_ms: int | None = None
    employee_id: int | None = None


class EventLogger:
    def __init__(self, horizon_ms: int):
        self.horizon_ms = horizon_ms
        self._last_time_ms = -1

    def emit(self, time_ms: int, event: str, entity_type: str, entity: str, payload: dict) -> None:
        if time_ms > self.horizon_ms:
            return
        if time_ms < self._last_time_ms:
            raise RuntimeError("Events emitted out of time order")
        self._last_time_ms = time_ms

        obj = {
            "time": ms_to_seconds(time_ms),
            "time_str": ms_to_time_str(time_ms),
            "event": event,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload,
        }
        print(json.dumps(obj, separators=(",", ":")), flush=True)


def employee_name(employee_id: int) -> str:
    return f"Employee_{employee_id}"


def client_generator(
    env: simpy.Environment,
    horizon_ms: int,
    client_queue: simpy.Store,
    logger: EventLogger,
    rng: random.Random,
    client_mean: float,
    client_stddev: float,
):
    client_id = 0

    while True:
        now_ms = int(env.now)
        if now_ms > horizon_ms:
            break

        client_id += 1
        client = Client(client_id=client_id, arrived_ms=now_ms)

        logger.emit(
            now_ms,
            "client_generated",
            "client_generator",
            "ClientGenerator",
            {"client_id": client_id, "arrival_time": ms_to_seconds(now_ms)},
        )
        yield client_queue.put(client)

        interval_ms = sample_interval_ms(rng, client_mean, client_stddev)
        yield env.timeout(interval_ms)


def service_process(
    env: simpy.Environment,
    horizon_ms: int,
    idle_employees: simpy.Store,
    logger: EventLogger,
    rng: random.Random,
    client: Client,
    employee_id: int,
    employee_mean: float,
    employee_stddev: float,
):
    duration_ms = sample_service_ms(rng, employee_mean, employee_stddev)
    yield env.timeout(duration_ms)

    now_ms = int(env.now)
    if now_ms > horizon_ms:
        return

    arrived_s = ms_to_seconds(client.arrived_ms)
    dispatched_s = ms_to_seconds(now_ms)

    logger.emit(
        now_ms,
        "client_served",
        "employee",
        employee_name(employee_id),
        {
            "client_id": client.client_id,
            "employee_id": employee_id,
            "arrived": arrived_s,
            "dispatched": dispatched_s,
            "delay": round(dispatched_s - arrived_s, 3),
        },
    )

    logger.emit(
        now_ms,
        "employee_available",
        "employee",
        employee_name(employee_id),
        {"employee_id": employee_id},
    )
    yield idle_employees.put(employee_id)


def matcher(
    env: simpy.Environment,
    horizon_ms: int,
    client_queue: simpy.Store,
    idle_employees: simpy.Store,
    logger: EventLogger,
    rng: random.Random,
    employee_1_mean: float,
    employee_1_stddev: float,
    employee_2_mean: float,
    employee_2_stddev: float,
):
    while True:
        client: Client = yield client_queue.get()
        employee_id: int = yield idle_employees.get()

        now_ms = int(env.now)
        if now_ms > horizon_ms:
            return

        client.employee_id = employee_id
        client.paired_ms = now_ms

        logger.emit(
            now_ms,
            "client_paired",
            "queue",
            "Queue",
            {
                "client_id": client.client_id,
                "employee_id": employee_id,
                "paired_time": ms_to_seconds(now_ms),
            },
        )

        if employee_id == 1:
            mean, std = employee_1_mean, employee_1_stddev
        else:
            mean, std = employee_2_mean, employee_2_stddev

        env.process(
            service_process(
                env,
                horizon_ms,
                idle_employees,
                logger,
                rng,
                client,
                employee_id,
                mean,
                std,
            )
        )


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Two-employee store cashier DES simulation")
    p.add_argument(
        "--simulation_time",
        type=str,
        default="00:05:00:000",
        help='Total simulation horizon in HH:MM:SS:mmm (default: "00:05:00:000")',
    )
    p.add_argument("--client_mean", type=float, default=10.0)
    p.add_argument("--client_stddev", type=float, default=5.0)
    p.add_argument("--employee_1_mean", type=float, default=20.0)
    p.add_argument("--employee_1_stddev", type=float, default=0.0)
    p.add_argument("--employee_2_mean", type=float, default=30.0)
    p.add_argument("--employee_2_stddev", type=float, default=4.0)
    p.add_argument("--seed", type=int, default=0)
    return p


def main() -> None:
    args = build_arg_parser().parse_args()

    for name in (
        "client_mean",
        "client_stddev",
        "employee_1_mean",
        "employee_1_stddev",
        "employee_2_mean",
        "employee_2_stddev",
    ):
        if getattr(args, name) < 0:
            raise SystemExit(f"{name} must be non-negative")


    horizon_ms = parse_hhmmssmmm(args.simulation_time)
    rng = random.Random(args.seed)

    env = simpy.Environment(initial_time=0)

    client_queue = simpy.Store(env)
    idle_employees = simpy.Store(env)
    logger = EventLogger(horizon_ms=horizon_ms)

    # Initial availability at t = 0.0 must be emitted.
    for employee_id in (1, 2):
        logger.emit(
            0,
            "employee_available",
            "employee",
            employee_name(employee_id),
            {"employee_id": employee_id},
        )
        idle_employees.put(employee_id)

    env.process(
        client_generator(
            env,
            horizon_ms,
            client_queue,
            logger,
            rng,
            args.client_mean,
            args.client_stddev,
        )
    )
    env.process(
        matcher(
            env,
            horizon_ms,
            client_queue,
            idle_employees,
            logger,
            rng,
            args.employee_1_mean,
            args.employee_1_stddev,
            args.employee_2_mean,
            args.employee_2_stddev,
        )
    )

    run_until = horizon_ms if horizon_ms > 0 else 1e-9
    env.run(until=run_until)


if __name__ == "__main__":
    main()
