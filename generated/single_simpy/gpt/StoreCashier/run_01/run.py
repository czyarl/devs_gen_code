#!/usr/bin/env python3
import argparse
import json
import sys
import math
import random
from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Tuple

import simpy


def parse_hhmmssmmm(s: str) -> float:
    """Parse HH:MM:SS:mmm into seconds (float)."""
    parts = s.strip().split(":")
    if len(parts) != 4:
        raise ValueError("simulation_time must be in HH:MM:SS:mmm format")
    hh, mm, ss, mmm = parts
    h = int(hh)
    m = int(mm)
    sec = int(ss)
    ms = int(mmm)
    if not (0 <= m < 60 and 0 <= sec < 60 and 0 <= ms < 1000 and h >= 0):
        raise ValueError("Invalid time components in HH:MM:SS:mmm")
    return h * 3600 + m * 60 + sec + ms / 1000.0


def format_hhmmssmmm(t: float) -> str:
    """Format seconds (float) into HH:MM:SS:mmm with millisecond rounding."""
    if t < 0:
        t = 0.0
    # round to nearest millisecond for stable formatting
    total_ms = int(round(t * 1000.0))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def bounded_normal(rng: random.Random, mean: float, stddev: float, lo: float, hi: float) -> float:
    """Sample from normal and clamp to [lo, hi]. If stddev==0 => mean."""
    if stddev == 0.0:
        return float(mean)
    # Use gaussian then clamp (allowed by spec: "sampled from or otherwise chosen within")
    v = rng.gauss(mean, stddev)
    return float(clamp(v, lo, hi))


@dataclass
class Client:
    client_id: int
    arrival_time: float


class EventLogger:
    def __init__(self, horizon: float, out_stream):
        self.horizon = horizon
        self.out = out_stream
        self.last_time = -math.inf

    def emit(self, time: float, event: str, entity_type: str, entity: str, payload: Dict[str, Any]):
        # Do not emit events after horizon
        if time > self.horizon + 1e-12:
            return
        # Enforce nondecreasing time order
        if time + 1e-12 < self.last_time:
            raise RuntimeError(f"Event time decreased: {time} < {self.last_time}")
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


class StoreSimulation:
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
    ):
        self.env = env
        self.logger = logger
        self.horizon = horizon
        self.rng = rng

        self.client_mean = float(client_mean)
        self.client_stddev = float(client_stddev)

        self.emp_params = {
            1: (float(emp1_mean), float(emp1_stddev)),
            2: (float(emp2_mean), float(emp2_stddev)),
        }

        self.queue: List[Client] = []
        self.available_employees: List[int] = []  # employee ids currently idle
        self.next_client_id = 1

        # Track pairing times for service duration derivation (not output)
        self.paired_time: Dict[int, float] = {}
        self.client_arrival: Dict[int, float] = {}

    def client_interarrival(self) -> float:
        lo = 0.0
        hi = self.client_mean + 5.0 * self.client_stddev
        # If stddev is 0, interval must equal mean within tolerance, and mean must be within [0, mean]
        if self.client_stddev == 0.0:
            return float(clamp(self.client_mean, lo, hi))
        return bounded_normal(self.rng, self.client_mean, self.client_stddev, lo, hi)

    def service_duration(self, employee_id: int) -> float:
        mean, std = self.emp_params[employee_id]
        lo = mean - 3.0 * std
        hi = mean + 3.0 * std
        if std == 0.0:
            return float(mean)
        return bounded_normal(self.rng, mean, std, lo, hi)

    def emit_employee_available(self, employee_id: int):
        self.logger.emit(
            time=self.env.now,
            event="employee_available",
            entity_type="employee",
            entity=f"Employee_{employee_id}",
            payload={"employee_id": employee_id},
        )

    def emit_client_generated(self, client_id: int, arrival_time: float):
        self.logger.emit(
            time=self.env.now,
            event="client_generated",
            entity_type="client_generator",
            entity="ClientGenerator",
            payload={"client_id": client_id, "arrival_time": float(arrival_time)},
        )

    def emit_client_paired(self, client_id: int, employee_id: int, paired_time: float):
        self.logger.emit(
            time=self.env.now,
            event="client_paired",
            entity_type="queue",
            entity="Queue",
            payload={"client_id": client_id, "employee_id": employee_id, "paired_time": float(paired_time)},
        )

    def emit_client_served(self, client_id: int, employee_id: int, arrived: float, dispatched: float):
        delay = float(dispatched - arrived)
        self.logger.emit(
            time=self.env.now,
            event="client_served",
            entity_type="employee",
            entity=f"Employee_{employee_id}",
            payload={
                "client_id": client_id,
                "employee_id": employee_id,
                "arrived": float(arrived),
                "dispatched": float(dispatched),
                "delay": delay,
            },
        )

    def try_pair(self):
        """
        Pair as many as possible at current time.
        FIFO: always take earliest waiting client.
        Employee selection: smallest employee id among available (deterministic).
        """
        self.available_employees.sort()
        while self.queue and self.available_employees:
            emp_id = self.available_employees.pop(0)
            client = self.queue.pop(0)
            paired_time = float(self.env.now)

            self.paired_time[client.client_id] = paired_time
            self.emit_client_paired(client.client_id, emp_id, paired_time)

            # Start service process
            self.env.process(self.employee_service(emp_id, client))

    def employee_service(self, employee_id: int, client: Client):
        dur = self.service_duration(employee_id)
        # If service would complete after horizon, do not emit completion or availability after horizon
        yield self.env.timeout(dur)

        dispatched = float(self.env.now)
        # Emit served (if within horizon) and then availability (if within horizon)
        self.emit_client_served(client.client_id, employee_id, client.arrival_time, dispatched)

        # Mark employee available and attempt pairing immediately
        self.available_employees.append(employee_id)
        self.emit_employee_available(employee_id)
        self.try_pair()

    def client_generator(self):
        # First client at t=0
        next_time = 0.0
        while True:
            # Wait until next arrival time
            if next_time > self.horizon + 1e-12:
                break
            # If env.now already equals next_time, timeout(0) is fine
            yield self.env.timeout(max(0.0, next_time - self.env.now))

            now = float(self.env.now)
            if now > self.horizon + 1e-12:
                break

            cid = self.next_client_id
            self.next_client_id += 1
            client = Client(client_id=cid, arrival_time=now)
            self.client_arrival[cid] = now

            self.emit_client_generated(cid, now)

            # Enqueue and try pairing
            self.queue.append(client)
            self.try_pair()

            # Schedule next arrival
            interval = self.client_interarrival()
            next_time = now + interval

    def initialize(self):
        # Employees initially available at t=0
        self.available_employees = [1, 2]
        # Emit initial availability events at t=0
        self.emit_employee_available(1)
        self.emit_employee_available(2)
        # Start generator
        self.env.process(self.client_generator())
        # Pair immediately if any (none at t=0 before generator runs, but generator also at t=0)
        # Pairing will happen when generator enqueues client at t=0


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Two-Employee Store Cashier Simulation (JSONL event log).")
    p.add_argument("--simulation_time", type=str, default="00:05:00:000", help="Horizon in HH:MM:SS:mmm")
    p.add_argument("--client_mean", type=float, default=10.0)
    p.add_argument("--client_stddev", type=float, default=5.0)
    p.add_argument("--employee_1_mean", type=float, default=20.0)
    p.add_argument("--employee_1_stddev", type=float, default=0.0)
    p.add_argument("--employee_2_mean", type=float, default=30.0)
    p.add_argument("--employee_2_stddev", type=float, default=4.0)
    p.add_argument("--seed", type=int, default=12345)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)

    horizon = parse_hhmmssmmm(args.simulation_time)
    if horizon < 0:
        raise ValueError("simulation_time must be nonnegative")

    rng = random.Random(args.seed)

    env = simpy.Environment()
    logger = EventLogger(horizon=horizon, out_stream=sys.stdout)

    sim = StoreSimulation(
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
    sim.initialize()

    # Run until horizon; SimPy will process events up to this time.
    env.run(until=horizon)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())