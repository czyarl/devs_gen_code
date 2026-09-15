#!/usr/bin/env python3
"""Two-Employee Store Cashier discrete-event simulation.

Entry point: python run.py
Emits JSONL events to stdout.

Implements the specification described in the PR description.
"""

from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import simpy


def parse_hhmmssmmm(value: str) -> float:
    """Parse HH:MM:SS:mmm into seconds (float)."""
    try:
        hh, mm, ss, mmm = value.split(":")
        h = int(hh)
        m = int(mm)
        s = int(ss)
        ms = int(mmm)
    except Exception as e:  # noqa: BLE001
        raise argparse.ArgumentTypeError(
            "--simulation_time must be in HH:MM:SS:mmm format"
        ) from e

    if h < 0 or m < 0 or s < 0 or ms < 0 or m >= 60 or s >= 60 or ms >= 1000:
        raise argparse.ArgumentTypeError(
            "--simulation_time must be in HH:MM:SS:mmm format"
        )
    return h * 3600 + m * 60 + s + ms / 1000.0


def format_hhmmssmmm(seconds: float) -> str:
    """Format seconds into HH:MM:SS:mmm."""
    if seconds < 0:
        seconds = 0.0
    # Round to nearest millisecond for stable formatting
    total_ms = int(round(seconds * 1000.0))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def sample_truncated_normal(
    rng: random.Random,
    mean: float,
    stddev: float,
    lo: float,
    hi: float,
) -> float:
    """Sample a normal value and clamp to [lo, hi].

    The spec allows values to be "sampled from or otherwise chosen within"
    the allowed range, so clamping is acceptable and deterministic.
    """
    if stddev == 0.0:
        # Must equal mean within floating tolerance
        return float(mean)
    val = rng.gauss(mean, stddev)
    return float(clamp(val, lo, hi))


@dataclass
class Client:
    client_id: int
    arrival_time: float


class EventLogger:
    def __init__(self) -> None:
        self._last_time: float = -math.inf

    def emit(
        self,
        time: float,
        event: str,
        entity_type: str,
        entity: str,
        payload: Dict[str, Any],
    ) -> None:
        # Ensure nondecreasing time order
        if time < self._last_time - 1e-12:
            raise RuntimeError("Events emitted out of order")
        self._last_time = time
        obj = {
            "time": float(time),
            "time_str": format_hhmmssmmm(time),
            "event": event,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload,
        }
        print(json.dumps(obj, separators=(",", ":")))


class CashierSystem:
    def __init__(
        self,
        env: simpy.Environment,
        logger: EventLogger,
        horizon: float,
        rng: random.Random,
        client_mean: float,
        client_stddev: float,
        emp1_mean: float,
        emp1_stddev: float,
        emp2_mean: float,
        emp2_stddev: float,
    ) -> None:
        self.env = env
        self.logger = logger
        self.horizon = horizon
        self.rng = rng

        self.client_mean = client_mean
        self.client_stddev = client_stddev

        self.emp_params = {
            1: (emp1_mean, emp1_stddev),
            2: (emp2_mean, emp2_stddev),
        }

        self.queue: simpy.Store[Client] = simpy.Store(env)
        self.available_employees: simpy.Store[int] = simpy.Store(env)

        self._next_client_id = 1

    def _emit_if_within_horizon(self, time: float, *args: Any, **kwargs: Any) -> None:
        if time <= self.horizon + 1e-12:
            self.logger.emit(time, *args, **kwargs)

    def employee_process(self, employee_id: int) -> simpy.events.Event:
        # Initial availability at t=0
        self._emit_if_within_horizon(
            self.env.now,
            "employee_available",
            "employee",
            f"Employee_{employee_id}",
            {"employee_id": employee_id},
        )
        yield self.available_employees.put(employee_id)

        while True:
            client: Client = yield self.queue.get()
            paired_time = float(self.env.now)
            self._emit_if_within_horizon(
                paired_time,
                "client_paired",
                "queue",
                "Queue",
                {
                    "client_id": client.client_id,
                    "employee_id": employee_id,
                    "paired_time": paired_time,
                },
            )

            mean, std = self.emp_params[employee_id]
            lo = mean - 3.0 * std
            hi = mean + 3.0 * std
            duration = sample_truncated_normal(self.rng, mean, std, lo, hi)
            if duration < 0:
                duration = 0.0

            # Service
            yield self.env.timeout(duration)
            dispatched = float(self.env.now)
            self._emit_if_within_horizon(
                dispatched,
                "client_served",
                "employee",
                f"Employee_{employee_id}",
                {
                    "client_id": client.client_id,
                    "employee_id": employee_id,
                    "arrived": float(client.arrival_time),
                    "dispatched": dispatched,
                    "delay": float(dispatched - client.arrival_time),
                },
            )

            # Available again
            self._emit_if_within_horizon(
                dispatched,
                "employee_available",
                "employee",
                f"Employee_{employee_id}",
                {"employee_id": employee_id},
            )
            yield self.available_employees.put(employee_id)

    def dispatcher_process(self) -> simpy.events.Event:
        # Dispatcher pairs FIFO clients with available employees.
        while True:
            emp_id = yield self.available_employees.get()
            client: Client = yield self.queue.get()
            # Put back client for employee process to consume, but ensure pairing is immediate.
            # To keep a single source of truth for pairing/service, we directly start service here
            # by handing the client to a dedicated service routine.
            self.env.process(self._serve_client(emp_id, client))

    def _serve_client(self, employee_id: int, client: Client) -> simpy.events.Event:
        paired_time = float(self.env.now)
        self._emit_if_within_horizon(
            paired_time,
            "client_paired",
            "queue",
            "Queue",
            {
                "client_id": client.client_id,
                "employee_id": employee_id,
                "paired_time": paired_time,
            },
        )

        mean, std = self.emp_params[employee_id]
        lo = mean - 3.0 * std
        hi = mean + 3.0 * std
        duration = sample_truncated_normal(self.rng, mean, std, lo, hi)
        if duration < 0:
            duration = 0.0

        yield self.env.timeout(duration)
        dispatched = float(self.env.now)
        self._emit_if_within_horizon(
            dispatched,
            "client_served",
            "employee",
            f"Employee_{employee_id}",
            {
                "client_id": client.client_id,
                "employee_id": employee_id,
                "arrived": float(client.arrival_time),
                "dispatched": dispatched,
                "delay": float(dispatched - client.arrival_time),
            },
        )

        self._emit_if_within_horizon(
            dispatched,
            "employee_available",
            "employee",
            f"Employee_{employee_id}",
            {"employee_id": employee_id},
        )
        yield self.available_employees.put(employee_id)

    def client_generator_process(self) -> simpy.events.Event:
        # First client at t=0
        while True:
            now = float(self.env.now)
            if now > self.horizon + 1e-12:
                return

            client_id = self._next_client_id
            self._next_client_id += 1
            client = Client(client_id=client_id, arrival_time=now)
            self._emit_if_within_horizon(
                now,
                "client_generated",
                "client_generator",
                "ClientGenerator",
                {"client_id": client_id, "arrival_time": now},
            )
            yield self.queue.put(client)

            # Next arrival interval
            lo = 0.0
            hi = self.client_mean + 5.0 * self.client_stddev
            interval = sample_truncated_normal(
                self.rng, self.client_mean, self.client_stddev, lo, hi
            )
            if interval < 0:
                interval = 0.0
            yield self.env.timeout(interval)


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
    p.add_argument("--seed", type=int, default=None)
    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    horizon = parse_hhmmssmmm(args.simulation_time)

    rng = random.Random(args.seed)
    env = simpy.Environment()
    logger = EventLogger()

    system = CashierSystem(
        env=env,
        logger=logger,
        horizon=horizon,
        rng=rng,
        client_mean=args.client_mean,
        client_stddev=args.client_stddev,
        emp1_mean=args.employee_1_mean,
        emp1_stddev=args.employee_1_stddev,
        emp2_mean=args.employee_2_mean,
        emp2_stddev=args.employee_2_stddev,
    )

    # Initial employee availability events at t=0
    system._emit_if_within_horizon(
        0.0,
        "employee_available",
        "employee",
        "Employee_1",
        {"employee_id": 1},
    )
    system._emit_if_within_horizon(
        0.0,
        "employee_available",
        "employee",
        "Employee_2",
        {"employee_id": 2},
    )
    # Put employees into availability pool
    env.process(system.client_generator_process())
    env.process(system.dispatcher_process())
    system.available_employees.put(1)
    system.available_employees.put(2)

    env.run(until=horizon)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
