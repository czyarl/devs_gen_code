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
        hh_i = int(hh)
        mm_i = int(mm)
        ss_i = int(ss)
        mmm_i = int(mmm)
    except ValueError as e:
        raise argparse.ArgumentTypeError("simulation_time must be numeric") from e
    if not (0 <= mm_i < 60 and 0 <= ss_i < 60 and 0 <= mmm_i < 1000 and hh_i >= 0):
        raise argparse.ArgumentTypeError("simulation_time has out-of-range fields")
    return hh_i * 3600.0 + mm_i * 60.0 + ss_i + (mmm_i / 1000.0)


def format_hhmmssmmm(t: float) -> str:
    """Format seconds into HH:MM:SS:mmm (milliseconds truncated)."""
    if t < 0:
        t = 0.0
    total_ms = int(math.floor(t * 1000.0 + 1e-9))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"


def bounded_normal(rng: random.Random, mean: float, stddev: float, lo: float, hi: float) -> float:
    """Sample from a normal distribution and clamp to [lo, hi].

    Spec allows values "sampled from or otherwise chosen within" the range.
    Clamping keeps determinism and stays within bounds.
    """
    if stddev == 0.0:
        # Must equal mean within tolerance.
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


class EventLogger:
    def __init__(self, horizon: float):
        self.horizon = float(horizon)

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
            "time_str": format_hhmmssmmm(float(time)),
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
        self.horizon = float(horizon)

        self.client_mean = float(client_mean)
        self.client_stddev = float(client_stddev)

        self.emp_params = {
            1: (float(emp1_mean), float(emp1_stddev)),
            2: (float(emp2_mean), float(emp2_stddev)),
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

    def emit_client_paired(self, client_id: int, employee_id: int, paired_time: float) -> None:
        self.logger.emit(
            paired_time,
            "client_paired",
            "queue",
            "Queue",
            {"client_id": client_id, "employee_id": employee_id, "paired_time": float(paired_time)},
        )

    def emit_client_served(
        self,
        employee_id: int,
        client: Client,
        dispatched: float,
    ) -> None:
        delay = float(dispatched - client.arrival_time)
        self.logger.emit(
            dispatched,
            "client_served",
            "employee",
            self.employee_name(employee_id),
            {
                "client_id": client.client_id,
                "employee_id": employee_id,
                "arrived": float(client.arrival_time),
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

            client = Client(client_id=self.next_client_id, arrival_time=now)
            self.next_client_id += 1
            self.emit_client_generated(client)
            yield self.queue.put(client)

            # Next inter-arrival
            lo = 0.0
            hi = self.client_mean + 5.0 * self.client_stddev
            interval = bounded_normal(self.rng, self.client_mean, self.client_stddev, lo, hi)
            # If next arrival would be after horizon, we can stop early to avoid extra events.
            if now + interval > self.horizon + 1e-12:
                return
            yield self.env.timeout(interval)

    def employee_process(self, employee_id: int):
        # Initially available at t=0.0
        self.emit_employee_available(employee_id)
        yield self.available_employees.put(employee_id)

        while True:
            # Wait until there is a client to serve.
            client: Client = yield self.queue.get()
            paired_time = float(self.env.now)
            self.emit_client_paired(client.client_id, employee_id, paired_time)

            mean, stddev = self.emp_params[employee_id]
            lo = mean - 3.0 * stddev
            hi = mean + 3.0 * stddev
            duration = bounded_normal(self.rng, mean, stddev, lo, hi)

            # If service completion would be after horizon, do not emit completion/availability.
            if paired_time + duration > self.horizon + 1e-12:
                return

            yield self.env.timeout(duration)
            dispatched = float(self.env.now)
            self.emit_client_served(employee_id, client, dispatched)

            # Employee becomes available again.
            self.emit_employee_available(employee_id)
            yield self.available_employees.put(employee_id)

    def dispatcher(self):
        """Ensure immediate pairing when both a waiting client and an available employee exist.

        We implement pairing by having employees pull from the queue, but we must
        ensure FIFO and that an employee only serves when it is available.

        This dispatcher gates employees: it releases an employee to start service
        only when a client is waiting.
        """
        # In this model, employees already block on queue.get(), which ensures FIFO.
        # The available_employees store is kept only to satisfy the conceptual model;
        # no additional dispatcher logic is required.
        yield self.env.timeout(0)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Two-employee store cashier DES simulation")
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


def main(argv: Optional[list] = None) -> None:
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

    env.process(system.client_generator())
    env.process(system.employee_process(1))
    env.process(system.employee_process(2))

    # Run deterministically until horizon.
    env.run(until=horizon)


if __name__ == "__main__":
    main()
