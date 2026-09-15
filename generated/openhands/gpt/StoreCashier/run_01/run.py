import argparse
import json
import random
import sys
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
            "simulation_time must contain only integers"
        ) from e

    if any(x < 0 for x in (hh, mm, ss, mmm)):
        raise argparse.ArgumentTypeError("simulation_time fields must be nonnegative")
    if mm >= 60 or ss >= 60 or mmm >= 1000:
        raise argparse.ArgumentTypeError("invalid time; expected MM<60, SS<60, mmm<1000")

    return (((hh * 60 + mm) * 60 + ss) * 1000) + mmm


def format_hhmmssmmm(ms: int) -> str:
    if ms < 0:
        ms = 0
    mmm = ms % 1000
    total_s = ms // 1000
    ss = total_s % 60
    total_m = total_s // 60
    mm = total_m % 60
    hh = total_m // 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{mmm:03d}"


def sec(ms: int) -> float:
    return ms / 1000.0


def ms_from_seconds(seconds: float) -> int:
    return int(round(seconds * 1000.0))


def sample_trunc_normal_seconds(
    rng: random.Random,
    mean: float,
    stddev: float,
    lo: float,
    hi: float,
) -> float:
    if stddev == 0.0:
        return float(mean)

    for _ in range(10_000):
        x = rng.gauss(mean, stddev)
        if lo <= x <= hi:
            return float(x)
    return float(min(max(mean, lo), hi))


@dataclass(frozen=True)
class Client:
    client_id: int
    arrival_ms: int


class EventLogger:
    def __init__(self, out: object):
        self._out = out

    def emit(self, time_ms: int, event: str, entity_type: str, entity: str, payload: dict) -> None:
        obj = {
            "time": sec(time_ms),
            "time_str": format_hhmmssmmm(time_ms),
            "event": event,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload,
        }
        self._out.write(json.dumps(obj) + "\n")
        self._out.flush()


def employee_name(employee_id: int) -> str:
    return f"Employee_{employee_id}"


class StoreCashierSim:
    def __init__(
        self,
        *,
        horizon_ms: int,
        client_mean: float,
        client_stddev: float,
        employee_1_mean: float,
        employee_1_stddev: float,
        employee_2_mean: float,
        employee_2_stddev: float,
        seed: int,
        out: object,
    ):
        self.horizon_ms = horizon_ms
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.employee_mean = {1: employee_1_mean, 2: employee_2_mean}
        self.employee_stddev = {1: employee_1_stddev, 2: employee_2_stddev}
        self.rng = random.Random(seed)

        self.env = simpy.Environment(initial_time=0)
        self.logger = EventLogger(out)

        self.waiting_clients: simpy.Store[Client] = simpy.Store(self.env)
        self.available_employees: simpy.Store[int] = simpy.Store(self.env)

        self.client_arrival_ms: dict[int, int] = {}
        self.client_paired_ms: dict[int, int] = {}
        self.client_employee: dict[int, int] = {}

    def _emit_employee_available(self, employee_id: int) -> None:
        t = int(self.env.now)
        self.logger.emit(
            t,
            "employee_available",
            "employee",
            employee_name(employee_id),
            {"employee_id": employee_id},
        )

    def _emit_client_generated(self, client_id: int, arrival_ms: int) -> None:
        self.logger.emit(
            arrival_ms,
            "client_generated",
            "client_generator",
            "ClientGenerator",
            {"client_id": client_id, "arrival_time": sec(arrival_ms)},
        )

    def _emit_client_paired(self, client_id: int, employee_id: int, paired_ms: int) -> None:
        self.logger.emit(
            paired_ms,
            "client_paired",
            "queue",
            "Queue",
            {
                "client_id": client_id,
                "employee_id": employee_id,
                "paired_time": sec(paired_ms),
            },
        )

    def _emit_client_served(self, client_id: int, employee_id: int, dispatched_ms: int) -> None:
        arrived_ms = self.client_arrival_ms[client_id]
        delay = sec(dispatched_ms - arrived_ms)
        self.logger.emit(
            dispatched_ms,
            "client_served",
            "employee",
            employee_name(employee_id),
            {
                "client_id": client_id,
                "employee_id": employee_id,
                "arrived": sec(arrived_ms),
                "dispatched": sec(dispatched_ms),
                "delay": delay,
            },
        )

    def _sample_client_interval_ms(self) -> int:
        hi = self.client_mean + 5.0 * self.client_stddev
        x = sample_trunc_normal_seconds(self.rng, self.client_mean, self.client_stddev, 0.0, hi)
        return max(0, ms_from_seconds(x))

    def _sample_employee_duration_ms(self, employee_id: int) -> int:
        mean = self.employee_mean[employee_id]
        std = self.employee_stddev[employee_id]
        lo = mean - 3.0 * std
        hi = mean + 3.0 * std
        x = sample_trunc_normal_seconds(self.rng, mean, std, lo, hi)
        return max(0, ms_from_seconds(x))

    def client_generator(self):
        client_id = 1
        while True:
            now_ms = int(self.env.now)
            if now_ms > self.horizon_ms:
                return

            self.client_arrival_ms[client_id] = now_ms
            self._emit_client_generated(client_id, now_ms)
            yield self.waiting_clients.put(Client(client_id=client_id, arrival_ms=now_ms))
            client_id += 1

            interval_ms = self._sample_client_interval_ms()
            next_ms = now_ms + interval_ms
            if next_ms > self.horizon_ms:
                return
            yield self.env.timeout(interval_ms)

    def dispatcher(self):
        while True:
            employee_id = yield self.available_employees.get()
            client: Client = yield self.waiting_clients.get()

            paired_ms = int(self.env.now)
            self.client_employee[client.client_id] = employee_id
            self.client_paired_ms[client.client_id] = paired_ms
            self._emit_client_paired(client.client_id, employee_id, paired_ms)

            self.env.process(self.employee_service(employee_id, client.client_id))

    def employee_service(self, employee_id: int, client_id: int):
        duration_ms = self._sample_employee_duration_ms(employee_id)
        yield self.env.timeout(duration_ms)

        dispatched_ms = int(self.env.now)
        self._emit_client_served(client_id, employee_id, dispatched_ms)

        self._emit_employee_available(employee_id)
        yield self.available_employees.put(employee_id)

    def run(self) -> None:
        for employee_id in (1, 2):
            self._emit_employee_available(employee_id)
            self.available_employees.put(employee_id)

        self.env.process(self.client_generator())
        self.env.process(self.dispatcher())
        self.env.run(until=self.horizon_ms)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Two-employee store cashier DES simulation")
    p.add_argument(
        "--simulation_time",
        type=str,
        default="00:05:00:000",
        help='Total simulation horizon in "HH:MM:SS:mmm" (default: 00:05:00:000)',
    )

    p.add_argument("--client_mean", type=float, default=10.0)
    p.add_argument("--client_stddev", type=float, default=5.0)
    p.add_argument("--employee_1_mean", type=float, default=20.0)
    p.add_argument("--employee_1_stddev", type=float, default=0.0)
    p.add_argument("--employee_2_mean", type=float, default=30.0)
    p.add_argument("--employee_2_stddev", type=float, default=4.0)

    p.add_argument("--seed", type=int, default=0)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    horizon_ms = parse_hhmmssmmm(args.simulation_time)

    sim = StoreCashierSim(
        horizon_ms=horizon_ms,
        client_mean=args.client_mean,
        client_stddev=args.client_stddev,
        employee_1_mean=args.employee_1_mean,
        employee_1_stddev=args.employee_1_stddev,
        employee_2_mean=args.employee_2_mean,
        employee_2_stddev=args.employee_2_stddev,
        seed=args.seed,
        out=sys.stdout,
    )
    sim.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
