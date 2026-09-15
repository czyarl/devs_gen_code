import argparse
import json
import random
from dataclasses import dataclass
from typing import Optional

import simpy


def parse_hhmmssmmm(value: str) -> float:
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

    if mm < 0 or mm >= 60 or ss < 0 or ss >= 60 or mmm < 0 or mmm >= 1000:
        raise argparse.ArgumentTypeError(
            "simulation_time must be in HH:MM:SS:mmm format"
        )

    total_ms = ((hh * 60 + mm) * 60 + ss) * 1000 + mmm
    return total_ms / 1000.0


def format_hhmmssmmm(t: float) -> str:
    total_ms = int(round(t * 1000.0))
    if total_ms < 0:
        total_ms = 0

    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60

    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"


def quantize_ms(x: float) -> float:
    return round(x * 1000.0) / 1000.0


def sample_truncated_normal(
    rng: random.Random,
    mean: float,
    stddev: float,
    low: float,
    high: float,
) -> float:
    if stddev == 0.0:
        return float(mean)

    # Rejection sampling within inclusive bounds.
    while True:
        v = rng.gauss(mean, stddev)
        if low <= v <= high:
            return float(v)


@dataclass(frozen=True)
class Client:
    client_id: int
    arrival_time: float


class JsonlLogger:
    def __init__(self) -> None:
        self._last_time: float = -1.0

    def emit(
        self,
        *,
        time: float,
        event: str,
        entity_type: str,
        entity: str,
        payload: dict,
    ) -> None:
        qt = quantize_ms(time)
        if qt + 1e-12 < self._last_time:
            raise RuntimeError("Events must be emitted in nondecreasing time order")
        self._last_time = qt

        obj = {
            "time": qt,
            "time_str": format_hhmmssmmm(qt),
            "event": event,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload,
        }
        print(json.dumps(obj, separators=(",", ":")))


def client_generator(
    env: simpy.Environment,
    logger: JsonlLogger,
    queue: simpy.Store,
    horizon_s: float,
    rng: random.Random,
    client_mean: float,
    client_stddev: float,
):
    client_id = 1
    while True:
        now = quantize_ms(env.now)
        if now > horizon_s + 1e-12:
            return

        c = Client(client_id=client_id, arrival_time=now)
        logger.emit(
            time=now,
            event="client_generated",
            entity_type="client_generator",
            entity="ClientGenerator",
            payload={"client_id": c.client_id, "arrival_time": c.arrival_time},
        )
        yield queue.put(c)
        client_id += 1

        interval_high = client_mean + 5.0 * client_stddev
        interval = sample_truncated_normal(
            rng,
            mean=client_mean,
            stddev=client_stddev,
            low=0.0,
            high=interval_high,
        )
        interval = quantize_ms(interval)

        # Safety: avoid pathological zero-time infinite loops after quantization.
        if interval == 0.0:
            interval = 0.001

        yield env.timeout(interval)


def employee_process(
    env: simpy.Environment,
    logger: JsonlLogger,
    queue: simpy.Store,
    horizon_s: float,
    rng: random.Random,
    employee_id: int,
    service_mean: float,
    service_stddev: float,
):
    employee_entity = f"Employee_{employee_id}"

    def emit_available(t: float) -> None:
        logger.emit(
            time=t,
            event="employee_available",
            entity_type="employee",
            entity=employee_entity,
            payload={"employee_id": employee_id},
        )

    emit_available(quantize_ms(env.now))

    service_low = service_mean - 3.0 * service_stddev
    service_high = service_mean + 3.0 * service_stddev

    while True:
        client: Client = yield queue.get()
        paired_time = quantize_ms(env.now)
        if paired_time > horizon_s + 1e-12:
            return

        logger.emit(
            time=paired_time,
            event="client_paired",
            entity_type="queue",
            entity="Queue",
            payload={
                "client_id": client.client_id,
                "employee_id": employee_id,
                "paired_time": paired_time,
            },
        )

        duration = sample_truncated_normal(
            rng,
            mean=service_mean,
            stddev=service_stddev,
            low=service_low,
            high=service_high,
        )
        duration = quantize_ms(duration)
        if duration == 0.0:
            duration = 0.001

        yield env.timeout(duration)

        dispatched = quantize_ms(env.now)
        if dispatched > horizon_s + 1e-12:
            return

        delay = dispatched - client.arrival_time
        logger.emit(
            time=dispatched,
            event="client_served",
            entity_type="employee",
            entity=employee_entity,
            payload={
                "client_id": client.client_id,
                "employee_id": employee_id,
                "arrived": client.arrival_time,
                "dispatched": dispatched,
                "delay": delay,
            },
        )

        emit_available(dispatched)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Two-employee store cashier DES simulation")
    p.add_argument(
        "--simulation_time",
        type=str,
        default="00:05:00:000",
        help='Total simulation horizon in HH:MM:SS:mmm format (default "00:05:00:000")',
    )

    p.add_argument("--client_mean", type=float, default=10.0)
    p.add_argument("--client_stddev", type=float, default=5.0)
    p.add_argument("--employee_1_mean", type=float, default=20.0)
    p.add_argument("--employee_1_stddev", type=float, default=0.0)
    p.add_argument("--employee_2_mean", type=float, default=30.0)
    p.add_argument("--employee_2_stddev", type=float, default=4.0)
    p.add_argument("--seed", type=int, default=0)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    horizon_s = parse_hhmmssmmm(args.simulation_time)

    env = simpy.Environment()
    logger = JsonlLogger()
    queue = simpy.Store(env)
    rng = random.Random(args.seed)

    env.process(
        employee_process(
            env,
            logger,
            queue,
            horizon_s,
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
            horizon_s,
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

    # Ensure t=0 events occur even when horizon is 0.
    run_until = horizon_s if horizon_s > 0.0 else 1e-9
    env.run(until=run_until)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
