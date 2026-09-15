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
import sys
from dataclasses import dataclass
from typing import Any, Dict, Optional

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
            "--simulation_time must be in HH:MM:SS:mmm format with valid ranges"
        )

    return h * 3600 + m * 60 + s + ms / 1000.0


def format_hhmmssmmm(seconds: float) -> str:
    """Format seconds into HH:MM:SS:mmm."""
    if seconds < 0:
        seconds = 0.0
    # Avoid negative zero and floating artifacts
    total_ms = int(round(seconds * 1000.0 + 1e-9))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def sample_truncated_normal(rng: random.Random, mean: float, stddev: float, lo: float, hi: float) -> float:
    """Sample from a normal distribution and clamp to [lo, hi].

    The spec allows values to be "sampled from or otherwise chosen within" the range.
    Clamping is deterministic given the RNG and keeps values within bounds.
    """
    if stddev == 0.0:
        return float(mean)
    x = rng.gauss(mean, stddev)
    return float(clamp(x, lo, hi))


@dataclass
class Client:
    client_id: int
    arrival_time: float


class EventLogger:
    def __init__(self, out_stream):
        self.out = out_stream

    def emit(
        self,
        time: float,
        event: str,
        entity_type: str,
        entity: str,
        payload: Dict[str, Any],
    ) -> None:
        obj = {
            "time": float(time),
            "time_str": format_hhmmssmmm(float(time)),
            "event": event,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload,
        }
        self.out.write(json.dumps(obj, separators=(",", ":")) + "\n")


class CashierSystem:
    def __init__(
        self,
        env: simpy.Environment,
        logger: EventLogger,
        horizon: float,
        rng: random.Random,
        client_mean: float,
        client_stddev: float,
        employee_1_mean: float,
        employee_1_stddev: float,
        employee_2_mean: float,
        employee_2_stddev: float,
    ) -> None:
        self.env = env
        self.logger = logger
        self.horizon = horizon
        self.rng = rng

        self.client_mean = client_mean
        self.client_stddev = client_stddev

        self.employee_params = {
            1: (employee_1_mean, employee_1_stddev),
            2: (employee_2_mean, employee_2_stddev),
        }

        self.queue: simpy.Store[Client] = simpy.Store(env)
        self.available_employees: simpy.Store[int] = simpy.Store(env)

        self.next_client_id = 1
        self.client_arrival_times: Dict[int, float] = {}
        self.client_paired_times: Dict[int, float] = {}

    def _employee_entity(self, employee_id: int) -> str:
        return f"Employee_{employee_id}"

    def _emit_employee_available(self, employee_id: int) -> None:
        t = float(self.env.now)
        if t > self.horizon + 1e-12:
            return
        self.logger.emit(
            t,
            "employee_available",
            "employee",
            self._employee_entity(employee_id),
            {"employee_id": employee_id},
        )

    def _emit_client_generated(self, client_id: int, arrival_time: float) -> None:
        t = float(self.env.now)
        if t > self.horizon + 1e-12:
            return
        self.logger.emit(
            t,
            "client_generated",
            "client_generator",
            "ClientGenerator",
            {"client_id": client_id, "arrival_time": float(arrival_time)},
        )

    def _emit_client_paired(self, client_id: int, employee_id: int, paired_time: float) -> None:
        t = float(self.env.now)
        if t > self.horizon + 1e-12:
            return
        self.logger.emit(
            t,
            "client_paired",
            "queue",
            "Queue",
            {"client_id": client_id, "employee_id": employee_id, "paired_time": float(paired_time)},
        )

    def _emit_client_served(
        self,
        employee_id: int,
        client_id: int,
        arrived: float,
        dispatched: float,
    ) -> None:
        t = float(self.env.now)
        if t > self.horizon + 1e-12:
            return
        delay = float(dispatched - arrived)
        self.logger.emit(
            t,
            "client_served",
            "employee",
            self._employee_entity(employee_id),
            {
                "client_id": client_id,
                "employee_id": employee_id,
                "arrived": float(arrived),
                "dispatched": float(dispatched),
                "delay": delay,
            },
        )

    def client_generator(self):
        # First client at t=0.0
        while True:
            now = float(self.env.now)
            if now > self.horizon + 1e-12:
                return

            client_id = self.next_client_id
            self.next_client_id += 1
            self.client_arrival_times[client_id] = now
            self._emit_client_generated(client_id, now)
            yield self.queue.put(Client(client_id=client_id, arrival_time=now))

            # Next arrival
            lo = 0.0
            hi = self.client_mean + 5.0 * self.client_stddev
            interval = sample_truncated_normal(self.rng, self.client_mean, self.client_stddev, lo, hi)
            # Ensure non-negative and finite
            if not math.isfinite(interval) or interval < 0:
                interval = 0.0
            yield self.env.timeout(interval)

    def matcher(self):
        # Continuously pair FIFO clients with available employees.
        while True:
            employee_id = yield self.available_employees.get()
            client: Client = yield self.queue.get()

            paired_time = float(self.env.now)
            self.client_paired_times[client.client_id] = paired_time
            self._emit_client_paired(client.client_id, employee_id, paired_time)

            self.env.process(self.employee_service(employee_id, client))

    def employee_service(self, employee_id: int, client: Client):
        mean, stddev = self.employee_params[employee_id]
        lo = mean - 3.0 * stddev
        hi = mean + 3.0 * stddev
        duration = sample_truncated_normal(self.rng, mean, stddev, lo, hi)
        if not math.isfinite(duration):
            duration = float(mean)
        # If stddev==0, duration==mean already.

        yield self.env.timeout(duration)

        dispatched = float(self.env.now)
        arrived = self.client_arrival_times.get(client.client_id, client.arrival_time)
        self._emit_client_served(employee_id, client.client_id, arrived, dispatched)

        # Employee becomes available again
        self._emit_employee_available(employee_id)
        yield self.available_employees.put(employee_id)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Two-employee store cashier simulation")
    p.add_argument(
        "--simulation_time",
        type=str,
        default="00:05:00:000",
        help='Total simulation horizon in HH:MM:SS:mmm format (default: "00:05:00:000")',
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
    logger = EventLogger(sys.stdout)

    system = CashierSystem(
        env=env,
        logger=logger,
        horizon=horizon,
        rng=rng,
        client_mean=float(args.client_mean),
        client_stddev=float(args.client_stddev),
        employee_1_mean=float(args.employee_1_mean),
        employee_1_stddev=float(args.employee_1_stddev),
        employee_2_mean=float(args.employee_2_mean),
        employee_2_stddev=float(args.employee_2_stddev),
    )

    # Initial employee availability at t=0.0
    system._emit_employee_available(1)
    system._emit_employee_available(2)
    system.available_employees.put(1)
    system.available_employees.put(2)

    env.process(system.client_generator())
    env.process(system.matcher())

    env.run(until=horizon)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
