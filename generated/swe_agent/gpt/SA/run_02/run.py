#!/usr/bin/env python3
"""Airfreight logistics discrete-event simulation.

Entry point: python run.py

Outputs ONLY JSONL events to stdout. All debug/logging goes to stderr.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional

import simpy


def _emit(time: float, entity: str, event: str, payload: dict) -> None:
    """Emit one JSONL event to stdout."""
    sys.stdout.write(json.dumps({"time": float(time), "entity": entity, "event": event, "payload": payload}) + "\n")


@dataclass(frozen=True)
class Pallet:
    pallet_id: int
    gen_time: float
    expiration_time: float  # absolute simulation time


class LoadingQueue:
    """FIFO queue with active expiration."""

    def __init__(self, env: simpy.Environment):
        self.env = env
        self._order: Deque[int] = deque()
        self._items: Dict[int, Pallet] = {}
        self._size: int = 0
        self.total_expired: int = 0
        self.changed: simpy.Event = env.event()

    def __len__(self) -> int:
        return self._size

    def add(self, pallet: Pallet) -> None:
        self._order.append(pallet.pallet_id)
        self._items[pallet.pallet_id] = pallet
        self._size += 1

        _emit(
            self.env.now,
            "queue",
            "pallet_queued",
            {"pallet_id": pallet.pallet_id, "queue_size": self._size},
        )
        self._trigger_changed()

    def pop_next(self) -> Optional[Pallet]:
        while self._order:
            pid = self._order.popleft()
            pallet = self._items.pop(pid, None)
            if pallet is None:
                continue
            self._size -= 1
            self._trigger_changed()
            return pallet
        return None

    def expire(self, pallet_id: int) -> bool:
        pallet = self._items.pop(pallet_id, None)
        if pallet is None:
            return False
        self._size -= 1
        self.total_expired += 1

        _emit(
            self.env.now,
            "queue",
            "pallet_expired",
            {"pallet_id": pallet_id, "total_expired": self.total_expired},
        )
        self._trigger_changed()
        return True

    def _trigger_changed(self) -> None:
        if not self.changed.triggered:
            self.changed.succeed()
        self.changed = self.env.event()


class Facility:
    def __init__(
        self,
        env: simpy.Environment,
        queue: LoadingQueue,
        pallet_interval: float,
        pallet_expiration_time: float,
    ):
        self.env = env
        self.queue = queue
        self.pallet_interval = float(pallet_interval)
        self.pallet_expiration_time = float(pallet_expiration_time)
        self._next_id = 1

    def run(self):
        # Generate at t=0, t+interval, ...
        while True:
            gen_time = float(self.env.now)
            pallet_id = self._next_id
            self._next_id += 1
            expiration_time = gen_time + self.pallet_expiration_time

            _emit(
                self.env.now,
                "facility",
                "pallet_generated",
                {"pallet_id": pallet_id, "expiration_time": float(expiration_time)},
            )

            pallet = Pallet(pallet_id=pallet_id, gen_time=gen_time, expiration_time=expiration_time)
            self.queue.add(pallet)

            # Active expiration while the pallet is in the queue.
            # If the deadline is already reached, expire immediately (same simulation time)
            # before other components act on it.
            if expiration_time <= float(self.env.now):
                self.queue.expire(pallet.pallet_id)
            else:
                self.env.process(self._expire_at_deadline(pallet))

            yield self.env.timeout(self.pallet_interval)

    def _expire_at_deadline(self, pallet: Pallet):
        delay = float(pallet.expiration_time - self.env.now)
        if delay > 0:
            yield self.env.timeout(delay)
        # Expire exactly at deadline if still in queue.
        self.queue.expire(pallet.pallet_id)


class FleetCoordinator:
    def __init__(self, env: simpy.Environment, queue: LoadingQueue):
        self.env = env
        self.queue = queue
        self._idle: Deque["Aircraft"] = deque()
        self.changed: simpy.Event = env.event()

    def notify_idle(self, aircraft: "Aircraft") -> None:
        self._idle.append(aircraft)
        self._trigger_changed()

    def _trigger_changed(self) -> None:
        if not self.changed.triggered:
            self.changed.succeed()
        self.changed = self.env.event()

    def run(self):
        while True:
            made_assignment = False
            while self._idle and len(self.queue) > 0:
                aircraft = self._idle.popleft()
                pallet = self.queue.pop_next()
                if pallet is None:
                    break
                made_assignment = True
                _emit(
                    self.env.now,
                    "coordinator",
                    "assignment_created",
                    {"aircraft_id": aircraft.aircraft_id, "pallet_id": pallet.pallet_id},
                )
                aircraft.assign(pallet)

            if made_assignment:
                yield self.env.timeout(0)
                continue

            yield simpy.AnyOf(self.env, [self.queue.changed, self.changed])


class Aircraft:
    def __init__(
        self,
        env: simpy.Environment,
        coordinator: FleetCoordinator,
        aircraft_id: int,
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
    ):
        self.env = env
        self.coordinator = coordinator
        self.aircraft_id = int(aircraft_id)
        self.flight_time = float(flight_time)
        self.unload_time = float(unload_time)
        self.return_time = float(return_time)
        self.maintenance_time = float(maintenance_time)

        self._assigned_event: simpy.Event = env.event()
        self._assigned_pallet: Optional[Pallet] = None

    def assign(self, pallet: Pallet) -> None:
        self._assigned_pallet = pallet
        if not self._assigned_event.triggered:
            self._assigned_event.succeed()

    def run(self):
        self.coordinator.notify_idle(self)

        while True:
            yield self._assigned_event
            self._assigned_event = self.env.event()

            pallet = self._assigned_pallet
            self._assigned_pallet = None
            if pallet is None:
                self.coordinator.notify_idle(self)
                continue

            _emit(
                self.env.now,
                "aircraft",
                "depart",
                {"aircraft_id": self.aircraft_id, "pallet_id": pallet.pallet_id},
            )

            if self.flight_time > 0:
                yield self.env.timeout(self.flight_time)

            if self.unload_time > 0:
                yield self.env.timeout(self.unload_time)

            latency = float(self.env.now) - float(pallet.gen_time)
            _emit(
                self.env.now,
                "destination",
                "pallet_delivered",
                {"pallet_id": pallet.pallet_id, "aircraft_id": self.aircraft_id, "latency": float(latency)},
            )

            if self.return_time > 0:
                yield self.env.timeout(self.return_time)

            _emit(self.env.now, "aircraft", "return", {"aircraft_id": self.aircraft_id})

            _emit(self.env.now, "aircraft", "maintenance_start", {"aircraft_id": self.aircraft_id})
            if self.maintenance_time > 0:
                yield self.env.timeout(self.maintenance_time)
            _emit(self.env.now, "aircraft", "maintenance_end", {"aircraft_id": self.aircraft_id})

            self.coordinator.notify_idle(self)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Airfreight logistics DES simulation")
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
    if args.duration < 0:
        raise SystemExit("--duration must be >= 0")
    if args.num_aircraft < 1:
        raise SystemExit("--num_aircraft must be >= 1")
    if args.pallet_interval <= 0:
        raise SystemExit("--pallet_interval must be > 0")
    for name in [
        "pallet_expiration_time",
        "flight_time",
        "unload_time",
        "return_time",
        "maintenance_time",
    ]:
        if getattr(args, name) < 0:
            raise SystemExit(f"--{name} must be >= 0")


def main(argv: Optional[list[str]] = None) -> int:
    args = build_arg_parser().parse_args(argv)
    _validate_args(args)

    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(levelname)s: %(message)s")

    env = simpy.Environment()

    queue = LoadingQueue(env)
    coordinator = FleetCoordinator(env, queue)

    facility = Facility(
        env,
        queue,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
    )

    aircraft_list = [
        Aircraft(
            env,
            coordinator,
            aircraft_id=i + 1,
            flight_time=args.flight_time,
            unload_time=args.unload_time,
            return_time=args.return_time,
            maintenance_time=args.maintenance_time,
        )
        for i in range(args.num_aircraft)
    ]

    env.process(facility.run())
    env.process(coordinator.run())
    for a in aircraft_list:
        env.process(a.run())

    env.run(until=float(args.duration))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
