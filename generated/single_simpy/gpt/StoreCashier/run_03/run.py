#!/usr/bin/env python3
import argparse
import json
import logging
import math
import random
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import simpy


# -----------------------------
# Time formatting / parsing
# -----------------------------
def parse_hhmmssmmm(s: str) -> float:
    """
    Parse HH:MM:SS:mmm into seconds (float).
    """
    parts = s.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid time format '{s}', expected HH:MM:SS:mmm")
    hh, mm, ss, mmm = parts
    h = int(hh)
    m = int(mm)
    sec = int(ss)
    ms = int(mmm)
    if not (0 <= m < 60 and 0 <= sec < 60 and 0 <= ms < 1000 and h >= 0):
        raise ValueError(f"Invalid time value '{s}'")
    return h * 3600 + m * 60 + sec + ms / 1000.0


def format_hhmmssmmm(t: float) -> str:
    """
    Format seconds (float) into HH:MM:SS:mmm, rounding to nearest millisecond.
    """
    if t < 0:
        t = 0.0
    total_ms = int(round(t * 1000.0))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"


# -----------------------------
# Sampling helpers (bounded normal)
# -----------------------------
def bounded_normal(rng: random.Random, mean: float, stddev: float, lo: float, hi: float) -> float:
    """
    Sample from a normal distribution and clamp to [lo, hi].
    If stddev == 0, returns mean.
    """
    if stddev == 0.0:
        return float(mean)
    x = rng.gauss(mean, stddev)
    if x < lo:
        return float(lo)
    if x > hi:
        return float(hi)
    return float(x)


# -----------------------------
# Event logger
# -----------------------------
@dataclass
class EventLogger:
    horizon: float
    out: Any = sys.stdout
    last_time: float = field(default=0.0)

    def emit(self, time: float, event: str, entity_type: str, entity: str, payload: Dict[str, Any]) -> None:
        # Do not emit events after horizon
        if time > self.horizon + 1e-12:
            return

        # Enforce nondecreasing time order
        if time + 1e-12 < self.last_time:
            # This should not happen; log to stderr but still emit with corrected ordering not possible.
            logging.error("Event time decreased: %.6f -> %.6f for event %s", self.last_time, time, event)
        self.last_time = max(self.last_time, time)

        obj = {
            "time": float(time),
            "time_str": format_hhmmssmmm(time),
            "event": event,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload,
        }
        self.out.write(json.dumps(obj, separators=(",", ":")) + "\n")
        self.out.flush()


# -----------------------------
# Simulation model
# -----------------------------
@dataclass
class ClientInfo:
    client_id: int
    arrival_time: float
    paired_time: Optional[float] = None
    employee_id: Optional[int] = None


class StoreCashierSim:
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

        self.client_mean = float(client_mean)
        self.client_stddev = float(client_stddev)

        self.emp_params = {
            1: (float(emp1_mean), float(emp1_stddev)),
            2: (float(emp2_mean), float(emp2_stddev)),
        }

        self.queue: List[int] = []  # FIFO client ids
        self.clients: Dict[int, ClientInfo] = {}
        self.available_employees: List[int] = []  # employee ids currently idle

        self.next_client_id = 1

    def employee_entity(self, employee_id: int) -> str:
        return f"Employee_{employee_id}"

    def emit_employee_available(self, employee_id: int) -> None:
        self.logger.emit(
            time=self.env.now,
            event="employee_available",
            entity_type="employee",
            entity=self.employee_entity(employee_id),
            payload={"employee_id": employee_id},
        )

    def emit_client_generated(self, client_id: int, arrival_time: float) -> None:
        self.logger.emit(
            time=arrival_time,
            event="client_generated",
            entity_type="client_generator",
            entity="ClientGenerator",
            payload={"client_id": client_id, "arrival_time": float(arrival_time)},
        )

    def emit_client_paired(self, client_id: int, employee_id: int, paired_time: float) -> None:
        self.logger.emit(
            time=paired_time,
            event="client_paired",
            entity_type="queue",
            entity="Queue",
            payload={"client_id": client_id, "employee_id": employee_id, "paired_time": float(paired_time)},
        )

    def emit_client_served(self, client_id: int, employee_id: int, arrived: float, dispatched: float) -> None:
        delay = float(dispatched - arrived)
        self.logger.emit(
            time=dispatched,
            event="client_served",
            entity_type="employee",
            entity=self.employee_entity(employee_id),
            payload={
                "client_id": client_id,
                "employee_id": employee_id,
                "arrived": float(arrived),
                "dispatched": float(dispatched),
                "delay": delay,
            },
        )

    def try_pair(self) -> None:
        """
        Pair as many waiting clients with available employees as possible, FIFO.
        Pairing is instantaneous at current simulation time.
        """
        while self.queue and self.available_employees:
            client_id = self.queue.pop(0)
            employee_id = self.available_employees.pop(0)

            c = self.clients[client_id]
            c.paired_time = float(self.env.now)
            c.employee_id = employee_id

            self.emit_client_paired(client_id, employee_id, self.env.now)
            self.env.process(self.employee_service(employee_id, client_id))

    def employee_service(self, employee_id: int, client_id: int):
        """
        Serve the paired client for a sampled duration, then emit served and become available.
        """
        mean, std = self.emp_params[employee_id]
        if std == 0.0:
            duration = mean
        else:
            lo = mean - 3.0 * std
            hi = mean + 3.0 * std
            duration = bounded_normal(self.rng, mean, std, lo, hi)

        # Ensure nonnegative duration (should already be, but be safe)
        duration = max(0.0, float(duration))

        # If completion would be after horizon, do not emit completion event.
        completion_time = self.env.now + duration
        # Still advance simulation time deterministically; but we can stop emitting after horizon.
        yield self.env.timeout(duration)

        c = self.clients[client_id]
        # Emit served only if within horizon
        if self.env.now <= self.horizon + 1e-12:
            self.emit_client_served(client_id, employee_id, c.arrival_time, self.env.now)

        # Employee becomes available at completion time (emit only if within horizon)
        if self.env.now <= self.horizon + 1e-12:
            self.available_employees.append(employee_id)
            self.emit_employee_available(employee_id)
            self.try_pair()

    def client_generator(self):
        """
        Generate clients starting at t=0.0, then after bounded normal inter-arrival intervals.
        """
        # First at t=0.0
        while True:
            now = float(self.env.now)
            if now > self.horizon + 1e-12:
                return

            client_id = self.next_client_id
            self.next_client_id += 1

            self.clients[client_id] = ClientInfo(client_id=client_id, arrival_time=now)
            self.emit_client_generated(client_id, now)

            # Enqueue and try to pair immediately
            self.queue.append(client_id)
            self.try_pair()

            # Sample next inter-arrival
            lo = 0.0
            hi = self.client_mean + 5.0 * self.client_stddev
            # If stddev is 0, interval must equal mean, but also must respect bounds.
            interval = bounded_normal(self.rng, self.client_mean, self.client_stddev, lo, hi)
            interval = max(0.0, float(interval))

            # If next arrival would occur after horizon, we can stop scheduling further arrivals
            if self.env.now + interval > self.horizon + 1e-12:
                return
            yield self.env.timeout(interval)

    def initialize(self) -> None:
        # Employees initially available at t=0.0
        self.available_employees = [1, 2]
        self.emit_employee_available(1)
        self.emit_employee_available(2)

        # Start generator
        self.env.process(self.client_generator())


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Two-Employee Store Cashier simulation (deterministic time, JSONL events).")
    p.add_argument("--simulation_time", type=str, default="00:05:00:000", help="Simulation horizon HH:MM:SS:mmm")
    p.add_argument("--client_mean", type=float, default=10.0)
    p.add_argument("--client_stddev", type=float, default=5.0)
    p.add_argument("--employee_1_mean", type=float, default=20.0)
    p.add_argument("--employee_1_stddev", type=float, default=0.0)
    p.add_argument("--employee_2_mean", type=float, default=30.0)
    p.add_argument("--employee_2_stddev", type=float, default=4.0)
    p.add_argument("--seed", type=int, default=12345, help="RNG seed for reproducibility")
    p.add_argument("--log_level", type=str, default="WARNING", help="stderr log level (DEBUG, INFO, WARNING, ERROR)")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=getattr(logging, args.log_level.upper(), logging.WARNING))

    try:
        horizon = parse_hhmmssmmm(args.simulation_time)
    except ValueError as e:
        logging.error(str(e))
        return 2

    rng = random.Random(args.seed)
    env = simpy.Environment()

    logger = EventLogger(horizon=horizon, out=sys.stdout)

    sim = StoreCashierSim(
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
    sim.initialize()

    # Run until horizon; events after horizon are not emitted by logger.
    env.run(until=horizon)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())