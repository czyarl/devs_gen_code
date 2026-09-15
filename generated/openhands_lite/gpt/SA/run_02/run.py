#!/usr/bin/env python3
import argparse
import json
import logging
import sys
from collections import deque, namedtuple

import simpy


def _configure_logging() -> logging.Logger:
    logger = logging.getLogger("airfreight_sim")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def emit(time: float, entity: str, event: str, payload: dict) -> None:
    sys.stdout.write(json.dumps({"time": float(time), "entity": entity, "event": event, "payload": payload}) + "\n")


Pallet = namedtuple("Pallet", ["pallet_id", "generation_time", "expiration_time"])


class LoadingQueue:
    def __init__(self, env: simpy.Environment, *, logger: logging.Logger):
        self.env = env
        self.logger = logger
        self._fifo: deque[int] = deque()
        self._pallets: dict[int, Pallet] = {}
        self._expired_total = 0

        self._changed = env.event()

    def size(self) -> int:
        return len(self._pallets)

    def has_pallets(self) -> bool:
        return bool(self._pallets)

    def enqueue(self, pallet: Pallet) -> None:
        self._pallets[pallet.pallet_id] = pallet
        self._fifo.append(pallet.pallet_id)

        emit(self.env.now, "queue", "pallet_queued", {"pallet_id": pallet.pallet_id, "queue_size": self.size()})
        self._signal_changed()

        # Schedule an exact-time expiration event for this pallet.
        self.env.process(self._expire_at(pallet.pallet_id, pallet.expiration_time))

    def pop_next_fifo(self) -> Pallet | None:
        now = float(self.env.now)
        while self._fifo:
            pid = self._fifo.popleft()
            pallet = self._pallets.get(pid)
            if pallet is None:
                continue

            # Tie-breaking at the exact deadline: expiration wins over assignment.
            if float(pallet.expiration_time) <= now:
                self._pallets.pop(pid, None)
                self._expired_total += 1
                emit(float(pallet.expiration_time), "queue", "pallet_expired", {"pallet_id": pid, "total_expired": self._expired_total})
                self._signal_changed()
                continue

            self._pallets.pop(pid, None)
            self._signal_changed()
            return pallet
        return None

    def changed_event(self) -> simpy.Event:
        return self._changed

    def _signal_changed(self) -> None:
        if not self._changed.triggered:
            self._changed.succeed()
        self._changed = self.env.event()

    def _expire_at(self, pallet_id: int, expiration_time: float):
        delay = float(expiration_time) - float(self.env.now)
        if delay > 0:
            yield self.env.timeout(delay)
        # If still in queue at expiration time, expire immediately.
        pallet = self._pallets.pop(pallet_id, None)
        if pallet is None:
            return
        self._expired_total += 1
        now = float(self.env.now)
        if float(expiration_time) <= now:
            emit(float(expiration_time), "queue", "pallet_expired", {"pallet_id": pallet_id, "total_expired": self._expired_total})
        else:
            emit(now, "queue", "pallet_expired", {"pallet_id": pallet_id, "total_expired": self._expired_total})
        self._signal_changed()


class FleetCoordinator:
    def __init__(self, env: simpy.Environment, queue: LoadingQueue, *, logger: logging.Logger, duration: float):
        self.env = env
        self.queue = queue
        self.logger = logger
        self.duration = duration

        self._idle_aircraft: deque[int] = deque()
        self._aircraft_by_id: dict[int, "Aircraft"] = {}

        self._wakeup = env.event()
        self._proc = env.process(self._run())

    def register_aircraft(self, aircraft: "Aircraft") -> None:
        self._aircraft_by_id[aircraft.aircraft_id] = aircraft

    def aircraft_idle(self, aircraft_id: int) -> None:
        self._idle_aircraft.append(aircraft_id)
        self._signal_wakeup()

    def notify_queue_changed(self) -> None:
        self._signal_wakeup()

    def _signal_wakeup(self) -> None:
        if not self._wakeup.triggered:
            self._wakeup.succeed()
        self._wakeup = self.env.event()

    def _assign_one(self) -> bool:
        if not self._idle_aircraft:
            return False
        pallet = self.queue.pop_next_fifo()
        if pallet is None:
            return False

        aircraft_id = self._idle_aircraft.popleft()
        aircraft = self._aircraft_by_id[aircraft_id]

        emit(self.env.now, "coordinator", "assignment_created", {"aircraft_id": aircraft_id, "pallet_id": pallet.pallet_id})
        aircraft.assign(pallet)
        return True

    def _run(self):
        # Prime with a wakeup so we can attempt assignments at t=0.
        self._signal_wakeup()

        while True:
            if self.env.now >= self.duration:
                return

            while self._idle_aircraft and self.queue.has_pallets():
                if not self._assign_one():
                    break

            # Wait until something changes: aircraft idle, pallet arrives, or pallet expires.
            yield self.env.any_of([self._wakeup, self.queue.changed_event()])


class Aircraft:
    def __init__(
        self,
        env: simpy.Environment,
        *,
        aircraft_id: int,
        coordinator: FleetCoordinator,
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
        logger: logging.Logger,
    ):
        self.env = env
        self.aircraft_id = aircraft_id
        self.coordinator = coordinator
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.logger = logger

        self._assignments = simpy.Store(env, capacity=1)
        self._proc = env.process(self._run())

    def assign(self, pallet: Pallet) -> None:
        self._assignments.put(pallet)

    def _run(self):
        while True:
            pallet: Pallet = yield self._assignments.get()

            emit(self.env.now, "aircraft", "depart", {"aircraft_id": self.aircraft_id, "pallet_id": pallet.pallet_id})

            yield self.env.timeout(self.flight_time)
            yield self.env.timeout(self.unload_time)

            latency = self.env.now - pallet.generation_time
            emit(
                self.env.now,
                "destination",
                "pallet_delivered",
                {"pallet_id": pallet.pallet_id, "aircraft_id": self.aircraft_id, "latency": float(latency)},
            )

            yield self.env.timeout(self.return_time)
            emit(self.env.now, "aircraft", "return", {"aircraft_id": self.aircraft_id})

            emit(self.env.now, "aircraft", "maintenance_start", {"aircraft_id": self.aircraft_id})
            yield self.env.timeout(self.maintenance_time)
            emit(self.env.now, "aircraft", "maintenance_end", {"aircraft_id": self.aircraft_id})

            self.coordinator.aircraft_idle(self.aircraft_id)


class Facility:
    def __init__(
        self,
        env: simpy.Environment,
        queue: LoadingQueue,
        coordinator: FleetCoordinator,
        *,
        pallet_interval: float,
        pallet_expiration_time: float,
        duration: float,
        logger: logging.Logger,
    ):
        self.env = env
        self.queue = queue
        self.coordinator = coordinator
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.duration = duration
        self.logger = logger

        self._next_pallet_id = 1
        self._proc = env.process(self._run())

    def _run(self):
        # Generate pallets at t=0, t+interval, ... strictly before the horizon.
        while self.env.now < self.duration:
            pid = self._next_pallet_id
            self._next_pallet_id += 1

            gen_t = float(self.env.now)
            exp_t = gen_t + float(self.pallet_expiration_time)

            emit(gen_t, "facility", "pallet_generated", {"pallet_id": pid, "expiration_time": float(exp_t)})

            self.queue.enqueue(Pallet(pallet_id=pid, generation_time=gen_t, expiration_time=exp_t))
            self.coordinator.notify_queue_changed()

            yield self.env.timeout(self.pallet_interval)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Airfreight logistics DES simulator")
    p.add_argument("--duration", type=float, default=10000.0)
    p.add_argument("--num_aircraft", type=int, default=2)
    p.add_argument("--pallet_interval", type=float, default=25.0)
    p.add_argument("--pallet_expiration_time", type=float, default=150.0)
    p.add_argument("--flight_time", type=float, default=30.0)
    p.add_argument("--unload_time", type=float, default=2.0)
    p.add_argument("--return_time", type=float, default=30.0)
    p.add_argument("--maintenance_time", type=float, default=10.0)
    return p


def _validate_args(args: argparse.Namespace) -> None:
    if args.num_aircraft < 1:
        raise SystemExit("--num_aircraft must be >= 1")

    for name in [
        "duration",
        "pallet_interval",
        "pallet_expiration_time",
        "flight_time",
        "unload_time",
        "return_time",
        "maintenance_time",
    ]:
        v = getattr(args, name)
        if v < 0:
            raise SystemExit(f"--{name} must be >= 0")

    if args.pallet_interval <= 0:
        raise SystemExit("--pallet_interval must be > 0")

    # Safety: keep runtime bounded even for extreme parameter combinations.
    # This also bounds stdout volume so the program finishes quickly.
    max_aircraft = 10_000
    max_pallets = 25_000
    max_event_lines = 200_000

    if args.num_aircraft > max_aircraft:
        raise SystemExit(f"--num_aircraft too large (>{max_aircraft})")

    est_pallets = int(args.duration / args.pallet_interval) + 1 if args.duration >= 0 else 0
    if est_pallets > max_pallets:
        raise SystemExit(
            "Refusing to run: estimated pallet count too large "
            f"({est_pallets}). Increase --pallet_interval or reduce --duration."
        )

    # Worst-case output lines per pallet: generated + queued + (assignment, depart, delivered,
    # return, maintenance_start, maintenance_end) = 8.
    if est_pallets * 8 > max_event_lines:
        raise SystemExit(
            "Refusing to run: estimated event output too large "
            f"({est_pallets * 8} lines). Increase --pallet_interval or reduce --duration."
        )


def main(argv: list[str] | None = None) -> int:
    logger = _configure_logging()

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    _validate_args(args)

    env = simpy.Environment()

    queue = LoadingQueue(env, logger=logger)
    coordinator = FleetCoordinator(env, queue, logger=logger, duration=float(args.duration))

    aircraft_list: list[Aircraft] = []
    for i in range(1, args.num_aircraft + 1):
        ac = Aircraft(
            env,
            aircraft_id=i,
            coordinator=coordinator,
            flight_time=float(args.flight_time),
            unload_time=float(args.unload_time),
            return_time=float(args.return_time),
            maintenance_time=float(args.maintenance_time),
            logger=logger,
        )
        coordinator.register_aircraft(ac)
        aircraft_list.append(ac)

    # Initially, all aircraft are idle at the facility.
    for ac in aircraft_list:
        coordinator.aircraft_idle(ac.aircraft_id)

    facility = Facility(
        env,
        queue,
        coordinator,
        pallet_interval=float(args.pallet_interval),
        pallet_expiration_time=float(args.pallet_expiration_time),
        duration=float(args.duration),
        logger=logger,
    )

    # Run the simulation until the configured horizon.
    env.run(until=float(args.duration))
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
