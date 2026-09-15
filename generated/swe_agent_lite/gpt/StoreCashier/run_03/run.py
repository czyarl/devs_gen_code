import argparse
import json
import math
import random
from dataclasses import dataclass
from typing import Optional, Dict, Any

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
        hh_i = int(hh)
        mm_i = int(mm)
        ss_i = int(ss)
        mmm_i = int(mmm)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            "simulation_time must be in HH:MM:SS:mmm format"
        ) from e
    if mm_i < 0 or mm_i >= 60 or ss_i < 0 or ss_i >= 60 or mmm_i < 0 or mmm_i >= 1000:
        raise argparse.ArgumentTypeError(
            "simulation_time must be in HH:MM:SS:mmm format"
        )
    if hh_i < 0:
        raise argparse.ArgumentTypeError("simulation_time hours must be >= 0")
    return hh_i * 3600.0 + mm_i * 60.0 + ss_i + (mmm_i / 1000.0)


def format_hhmmssmmm(t: float) -> str:
    """Format seconds into HH:MM:SS:mmm (milliseconds truncated)."""
    if t < 0:
        t = 0.0
    # Avoid negative zero and floating artifacts
    total_ms = int(math.floor((t + 1e-9) * 1000.0))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def sample_interval(rng: random.Random, mean: float, stddev: float) -> float:
    """Client inter-arrival interval within [0, mean + 5*stddev]."""
    hi = mean + 5.0 * stddev
    if stddev <= 0.0:
        return clamp(mean, 0.0, hi)
    # Use normal then clamp to allowed range.
    return clamp(rng.gauss(mean, stddev), 0.0, hi)


def sample_service(rng: random.Random, mean: float, stddev: float) -> float:
    """Employee service duration within [mean-3*stddev, mean+3*stddev]."""
    if stddev == 0.0:
        return float(mean)
    lo = mean - 3.0 * stddev
    hi = mean + 3.0 * stddev
    return clamp(rng.gauss(mean, stddev), lo, hi)


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
        # Do not emit events after horizon.
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
        rng: random.Random,
        horizon: float,
        client_mean: float,
        client_stddev: float,
        employee_1_mean: float,
        employee_1_stddev: float,
        employee_2_mean: float,
        employee_2_stddev: float,
    ):
        self.env = env
        self.logger = logger
        self.rng = rng
        self.horizon = horizon

        self.client_mean = client_mean
        self.client_stddev = client_stddev

        self.employee_params = {
            1: (employee_1_mean, employee_1_stddev),
            2: (employee_2_mean, employee_2_stddev),
        }

        self.queue = simpy.Store(env)
        self.available_employees = simpy.Store(env)

        self.next_client_id = 1
        self.client_arrival: Dict[int, float] = {}
        self.client_paired_time: Dict[int, float] = {}

    def employee_entity(self, employee_id: int) -> str:
        return f"Employee_{employee_id}"

    def emit_employee_available(self, employee_id: int) -> None:
        self.logger.emit(
            self.env.now,
            "employee_available",
            "employee",
            self.employee_entity(employee_id),
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

    def emit_client_paired(self, client_id: int, employee_id: int) -> None:
        self.logger.emit(
            self.env.now,
            "client_paired",
            "queue",
            "Queue",
            {
                "client_id": client_id,
                "employee_id": employee_id,
                "paired_time": float(self.env.now),
            },
        )

    def emit_client_served(self, client_id: int, employee_id: int) -> None:
        arrived = self.client_arrival[client_id]
        dispatched = float(self.env.now)
        delay = dispatched - arrived
        self.logger.emit(
            self.env.now,
            "client_served",
            "employee",
            self.employee_entity(employee_id),
            {
                "client_id": client_id,
                "employee_id": employee_id,
                "arrived": float(arrived),
                "dispatched": float(dispatched),
                "delay": float(delay),
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
            client = Client(client_id=client_id, arrival_time=now)
            self.client_arrival[client_id] = now

            self.emit_client_generated(client)
            yield self.queue.put(client)

            interval = sample_interval(self.rng, self.client_mean, self.client_stddev)
            next_time = now + interval
            if next_time > self.horizon + 1e-12:
                return
            yield self.env.timeout(interval)

    def employee_process(self, employee_id: int):
        # Initial availability at t=0.0
        self.emit_employee_available(employee_id)
        yield self.available_employees.put(employee_id)

        while True:
            # Wait until both an employee token (this employee) is taken by dispatcher.
            # The dispatcher will start service by sending a (client_id, employee_id) job.
            job = yield self.env.process(self.wait_for_job(employee_id))
            if job is None:
                return
            client_id = job

            mean, stddev = self.employee_params[employee_id]
            duration = sample_service(self.rng, mean, stddev)
            end_time = self.env.now + duration
            if end_time > self.horizon + 1e-12:
                # Do not emit events after horizon; stop processing.
                return
            yield self.env.timeout(duration)

            self.emit_client_served(client_id, employee_id)
            self.emit_employee_available(employee_id)
            yield self.available_employees.put(employee_id)

    def wait_for_job(self, employee_id: int):
        # A simple per-employee mailbox implemented via Store.
        if not hasattr(self, "_mailboxes"):
            self._mailboxes: Dict[int, simpy.Store] = {
                1: simpy.Store(self.env),
                2: simpy.Store(self.env),
            }
        mailbox = self._mailboxes[employee_id]
        msg = yield mailbox.get()
        return msg

    def dispatcher(self):
        # Continuously pair FIFO clients with available employees.
        while True:
            if self.env.now > self.horizon + 1e-12:
                return
            client: Client = yield self.queue.get()
            employee_id: int = yield self.available_employees.get()

            # Pairing is instantaneous at current time.
            self.client_paired_time[client.client_id] = float(self.env.now)
            self.emit_client_paired(client.client_id, employee_id)

            # Send job to employee mailbox.
            if not hasattr(self, "_mailboxes"):
                self._mailboxes = {
                    1: simpy.Store(self.env),
                    2: simpy.Store(self.env),
                }
            yield self._mailboxes[employee_id].put(client.client_id)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Two-employee store cashier DES simulation")
    p.add_argument(
        "--simulation_time",
        type=str,
        default="00:05:00:000",
        help='Simulation horizon in HH:MM:SS:mmm (default: "00:05:00:000")',
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
        default=None,
        help="Optional RNG seed for reproducibility",
    )
    return p


def main(argv: Optional[list[str]] = None) -> None:
    args = build_arg_parser().parse_args(argv)
    horizon = parse_hhmmssmmm(args.simulation_time)

    rng = random.Random(args.seed)
    env = simpy.Environment()
    logger = EventLogger(horizon=horizon)

    sim = StoreCashierSim(
        env=env,
        logger=logger,
        rng=rng,
        horizon=horizon,
        client_mean=args.client_mean,
        client_stddev=args.client_stddev,
        employee_1_mean=args.employee_1_mean,
        employee_1_stddev=args.employee_1_stddev,
        employee_2_mean=args.employee_2_mean,
        employee_2_stddev=args.employee_2_stddev,
    )

    env.process(sim.client_generator())
    env.process(sim.dispatcher())
    env.process(sim.employee_process(1))
    env.process(sim.employee_process(2))

    env.run(until=horizon + 1e-9)


if __name__ == "__main__":
    main()
