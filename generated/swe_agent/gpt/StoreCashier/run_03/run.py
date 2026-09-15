#!/usr/bin/env python3
"""Two-Employee Store Cashier discrete-event simulation.

Entry point: python run.py

Emits JSONL events to stdout as specified in the PR description.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass
from typing import Any, Dict, Optional

import simpy


def parse_hhmmssmmm(value: str) -> float:
    """Parse HH:MM:SS:mmm into seconds (float)."""
    parts = value.split(":")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "--simulation_time must be in HH:MM:SS:mmm format"
        )
    try:
        hh, mm, ss, mmm = (int(p) for p in parts)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            "--simulation_time must be in HH:MM:SS:mmm format"
        ) from e
    if hh < 0 or mm < 0 or ss < 0 or mmm < 0 or mm >= 60 or ss >= 60 or mmm >= 1000:
        raise argparse.ArgumentTypeError(
            "--simulation_time must be in HH:MM:SS:mmm format with valid ranges"
        )
    return hh * 3600 + mm * 60 + ss + mmm / 1000.0


def format_hhmmssmmm(t: float) -> str:
    if t < 0:
        t = 0.0
    # Round to nearest millisecond for stable formatting
    total_ms = int(round(t * 1000.0))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"


def bounded_normal(rng: random.Random, mean: float, stddev: float, lo: float, hi: float) -> float:
    """Sample from a normal distribution but clamp to [lo, hi].

    The spec allows values to be "sampled from or otherwise chosen within" the range,
    so clamping is acceptable and deterministic given the RNG.
    """
    if stddev == 0.0:
        return float(mean)
    x = rng.gauss(mean, stddev)
    if x < lo:
        return float(lo)
    if x > hi:
        return float(hi)
    return float(x)


@dataclass
class Client:
    client_id: int
    arrival_time: float
    paired_time: Optional[float] = None


class EventLogger:
    def __init__(self, horizon: float):
        self.horizon = horizon

    def emit(self, time: float, event: str, entity_type: str, entity: str, payload: Dict[str, Any]) -> None:
        # Do not emit events after horizon
        if time > self.horizon + 1e-12:
            return
        obj = {
            "time": float(time),
            "time_str": format_hhmmssmmm(time),
            "event": event,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload,
        }
        print(json.dumps(obj, sort_keys=True))


class CashierSystem:
    def __init__(
        self,
        env: simpy.Environment,
        logger: EventLogger,
        rng: random.Random,
        horizon: float,
        client_mean: float,
        client_stddev: float,
        emp1_mean: float,
        emp1_stddev: float,
        emp2_mean: float,
        emp2_stddev: float,
    ):
        self.env = env
        self.logger = logger
        self.rng = rng
        self.horizon = horizon

        self.client_mean = client_mean
        self.client_stddev = client_stddev

        self.emp_params = {
            1: (emp1_mean, emp1_stddev),
            2: (emp2_mean, emp2_stddev),
        }

        self.queue: simpy.Store[Client] = simpy.Store(env)
        self.available_employees: simpy.Store[int] = simpy.Store(env)

        self.next_client_id = 1

    def employee_name(self, employee_id: int) -> str:
        return f"Employee_{employee_id}"

    def emit_employee_available(self, employee_id: int) -> None:
        self.logger.emit(
            self.env.now,
            "employee_available",
            "employee",
            self.employee_name(employee_id),
            {"employee_id": employee_id},
        )

    def emit_client_generated(self, client: Client) -> None:
        self.logger.emit(
            self.env.now,
            "client_generated",
            "client_generator",
            "ClientGenerator",
            {"client_id": client.client_id, "arrival_time": float(client.arrival_time)},
        )

    def emit_client_paired(self, client: Client, employee_id: int) -> None:
        self.logger.emit(
            self.env.now,
            "client_paired",
            "queue",
            "Queue",
            {
                "client_id": client.client_id,
                "employee_id": employee_id,
                "paired_time": float(client.paired_time if client.paired_time is not None else self.env.now),
            },
        )

    def emit_client_served(self, client: Client, employee_id: int) -> None:
        dispatched = float(self.env.now)
        arrived = float(client.arrival_time)
        delay = dispatched - arrived
        self.logger.emit(
            self.env.now,
            "client_served",
            "employee",
            self.employee_name(employee_id),
            {
                "client_id": client.client_id,
                "employee_id": employee_id,
                "arrived": arrived,
                "dispatched": dispatched,
                "delay": float(delay),
            },
        )

    def sample_interarrival(self) -> float:
        lo = 0.0
        hi = self.client_mean + 5.0 * self.client_stddev
        return bounded_normal(self.rng, self.client_mean, self.client_stddev, lo, hi)

    def sample_service(self, employee_id: int) -> float:
        mean, std = self.emp_params[employee_id]
        if std == 0.0:
            return float(mean)
        lo = mean - 3.0 * std
        hi = mean + 3.0 * std
        return bounded_normal(self.rng, mean, std, lo, hi)

    def client_generator(self):
        # First client at t=0
        while True:
            now = float(self.env.now)
            if now > self.horizon + 1e-12:
                return

            client = Client(client_id=self.next_client_id, arrival_time=now)
            self.next_client_id += 1
            self.emit_client_generated(client)
            yield self.queue.put(client)

            interval = self.sample_interarrival()
            next_time = self.env.now + interval
            if next_time > self.horizon + 1e-12:
                return
            yield self.env.timeout(interval)

    def pairing_manager(self):
        # Continuously pair FIFO clients with available employees.
        while True:
            client = yield self.queue.get()
            employee_id = yield self.available_employees.get()
            # Pairing is instantaneous at current time
            client.paired_time = float(self.env.now)
            self.emit_client_paired(client, employee_id)
            self.env.process(self.employee_service(employee_id, client))

    def employee_service(self, employee_id: int, client: Client):
        duration = self.sample_service(employee_id)
        end_time = self.env.now + duration
        if end_time > self.horizon + 1e-12:
            # Service completion would be after horizon; do not emit served/available.
            return
        yield self.env.timeout(duration)
        self.emit_client_served(client, employee_id)
        # Employee becomes available immediately after serving
        self.emit_employee_available(employee_id)
        yield self.available_employees.put(employee_id)


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
    p.add_argument("--seed", type=int, default=None)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    horizon = parse_hhmmssmmm(args.simulation_time)

    rng = random.Random(args.seed)
    env = simpy.Environment()
    logger = EventLogger(horizon=horizon)

    system = CashierSystem(
        env=env,
        logger=logger,
        rng=rng,
        horizon=horizon,
        client_mean=args.client_mean,
        client_stddev=args.client_stddev,
        emp1_mean=args.employee_1_mean,
        emp1_stddev=args.employee_1_stddev,
        emp2_mean=args.employee_2_mean,
        emp2_stddev=args.employee_2_stddev,
    )

    # Initial employee availability at t=0.0
    for emp_id in (1, 2):
        system.emit_employee_available(emp_id)
        # Store.put returns an Event; yield it from a tiny process to schedule at t=0
        def _put(eid: int):
            yield system.available_employees.put(eid)

        env.process(_put(emp_id))

    env.process(system.client_generator())
    env.process(system.pairing_manager())

    env.run(until=horizon)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
