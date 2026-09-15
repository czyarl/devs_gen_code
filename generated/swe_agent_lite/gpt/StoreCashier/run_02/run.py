import argparse
import json
import math
import random
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import simpy


def parse_hhmmssmmm(s: str) -> float:
    """Parse HH:MM:SS:mmm into seconds (float)."""
    parts = s.split(":")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "simulation_time must be in HH:MM:SS:mmm format"
        )
    hh, mm, ss, mmm = parts
    try:
        h = int(hh)
        m = int(mm)
        sec = int(ss)
        ms = int(mmm)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            "simulation_time must be in HH:MM:SS:mmm format"
        ) from e
    if m < 0 or m >= 60 or sec < 0 or sec >= 60 or ms < 0 or ms >= 1000 or h < 0:
        raise argparse.ArgumentTypeError(
            "simulation_time must be in HH:MM:SS:mmm format"
        )
    return h * 3600 + m * 60 + sec + ms / 1000.0


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


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass
class Client:
    client_id: int
    arrival_time: float


class EventLogger:
    def __init__(self, horizon: float):
        self.horizon = horizon

    def emit(
        self,
        time: float,
        event: str,
        entity_type: str,
        entity: str,
        payload: Dict[str, Any],
    ) -> None:
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
        print(json.dumps(obj, separators=(",", ":")))


class StoreCashierSim:
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

        self.client_mean = client_mean
        self.client_stddev = client_stddev

        self.emp_params = {
            1: (emp1_mean, emp1_stddev),
            2: (emp2_mean, emp2_stddev),
        }

        self.queue: simpy.Store[Client] = simpy.Store(env)
        self.available_employees: simpy.Store[int] = simpy.Store(env)

        self.next_client_id = 1
        self.client_arrival: Dict[int, float] = {}
        self.client_paired_time: Dict[int, float] = {}

    def sample_interarrival(self) -> float:
        # Allowed range: 0 <= interval <= mean + 5*stddev
        hi = self.client_mean + 5.0 * self.client_stddev
        if hi < 0:
            hi = 0.0
        if self.client_stddev <= 0:
            return clamp(self.client_mean, 0.0, hi)
        x = self.rng.normalvariate(self.client_mean, self.client_stddev)
        return clamp(x, 0.0, hi)

    def sample_service(self, employee_id: int) -> float:
        mean, std = self.emp_params[employee_id]
        if std == 0.0:
            return float(mean)
        lo = mean - 3.0 * std
        hi = mean + 3.0 * std
        x = self.rng.normalvariate(mean, std)
        return clamp(x, lo, hi)

    def employee_process(self, employee_id: int):
        entity = f"Employee_{employee_id}"
        # Initial availability at t=0
        self.logger.emit(
            self.env.now,
            "employee_available",
            "employee",
            entity,
            {"employee_id": employee_id},
        )
        yield self.available_employees.put(employee_id)

        while True:
            # Wait for a client
            client: Client = yield self.queue.get()
            paired_time = self.env.now
            self.client_paired_time[client.client_id] = paired_time
            self.logger.emit(
                paired_time,
                "client_paired",
                "queue",
                "Queue",
                {
                    "client_id": client.client_id,
                    "employee_id": employee_id,
                    "paired_time": float(paired_time),
                },
            )

            duration = self.sample_service(employee_id)
            done_time = paired_time + duration
            # If completion would be after horizon, do not emit completion/availability.
            if done_time > self.horizon + 1e-12:
                # Still advance time deterministically to horizon and stop.
                remaining = max(0.0, self.horizon - paired_time)
                if remaining > 0:
                    yield self.env.timeout(remaining)
                return

            yield self.env.timeout(duration)
            dispatched = self.env.now
            arrived = self.client_arrival[client.client_id]
            delay = dispatched - arrived
            self.logger.emit(
                dispatched,
                "client_served",
                "employee",
                entity,
                {
                    "client_id": client.client_id,
                    "employee_id": employee_id,
                    "arrived": float(arrived),
                    "dispatched": float(dispatched),
                    "delay": float(delay),
                },
            )

            # Employee becomes available again
            self.logger.emit(
                dispatched,
                "employee_available",
                "employee",
                entity,
                {"employee_id": employee_id},
            )
            yield self.available_employees.put(employee_id)

    def dispatcher_process(self):
        # Pairs waiting clients with available employees immediately.
        while True:
            emp_id = yield self.available_employees.get()
            client = yield self.queue.get()
            # Put back employee id? No: employee process itself will serve.
            # Instead, we need to hand the client to that specific employee.
            # Implement by routing via per-employee inbox.
            raise RuntimeError("dispatcher_process should not be used")

    def client_generator_process(self):
        t = 0.0
        while True:
            if t > self.horizon + 1e-12:
                return
            # Generate client at current time
            cid = self.next_client_id
            self.next_client_id += 1
            arrival_time = self.env.now
            self.client_arrival[cid] = arrival_time
            self.logger.emit(
                arrival_time,
                "client_generated",
                "client_generator",
                "ClientGenerator",
                {"client_id": cid, "arrival_time": float(arrival_time)},
            )
            yield self.queue.put(Client(cid, arrival_time))

            interval = self.sample_interarrival()
            t_next = self.env.now + interval
            if t_next > self.horizon + 1e-12:
                return
            yield self.env.timeout(interval)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Two-Employee Store Cashier DES simulation")
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
    logger = EventLogger(horizon=horizon)

    sim = StoreCashierSim(
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

    # Use per-employee inboxes to ensure pairing with a specific employee.
    inboxes: Dict[int, simpy.Store[Client]] = {1: simpy.Store(env), 2: simpy.Store(env)}

    def employee_proc(employee_id: int):
        entity = f"Employee_{employee_id}"
        sim.logger.emit(
            env.now,
            "employee_available",
            "employee",
            entity,
            {"employee_id": employee_id},
        )
        yield sim.available_employees.put(employee_id)
        while True:
            client: Client = yield inboxes[employee_id].get()
            paired_time = env.now
            sim.client_paired_time[client.client_id] = paired_time
            sim.logger.emit(
                paired_time,
                "client_paired",
                "queue",
                "Queue",
                {
                    "client_id": client.client_id,
                    "employee_id": employee_id,
                    "paired_time": float(paired_time),
                },
            )
            duration = sim.sample_service(employee_id)
            done_time = paired_time + duration
            if done_time > sim.horizon + 1e-12:
                remaining = max(0.0, sim.horizon - paired_time)
                if remaining > 0:
                    yield env.timeout(remaining)
                return
            yield env.timeout(duration)
            dispatched = env.now
            arrived = sim.client_arrival[client.client_id]
            delay = dispatched - arrived
            sim.logger.emit(
                dispatched,
                "client_served",
                "employee",
                entity,
                {
                    "client_id": client.client_id,
                    "employee_id": employee_id,
                    "arrived": float(arrived),
                    "dispatched": float(dispatched),
                    "delay": float(delay),
                },
            )
            sim.logger.emit(
                dispatched,
                "employee_available",
                "employee",
                entity,
                {"employee_id": employee_id},
            )
            yield sim.available_employees.put(employee_id)

    def dispatcher():
        # Ensure FIFO: take next client, then next available employee.
        while True:
            client: Client = yield sim.queue.get()
            emp_id: int = yield sim.available_employees.get()
            # Pairing is instantaneous at current time; employee will log paired.
            yield inboxes[emp_id].put(client)

    env.process(employee_proc(1))
    env.process(employee_proc(2))
    env.process(sim.client_generator_process())
    env.process(dispatcher())

    env.run(until=horizon)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
