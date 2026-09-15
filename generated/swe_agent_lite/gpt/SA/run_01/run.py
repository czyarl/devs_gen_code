#!/usr/bin/env python3
"""Airfreight logistics DES simulation.

Entry point: python run.py

Requirements implemented:
- argparse CLI
- JSONL events to stdout only
- logs/debug to stderr
- Discrete-event simulation using simpy
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Tuple

import simpy


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )


def emit(time: float, entity: str, event: str, payload: dict) -> None:
    """Emit a single JSONL event to stdout."""
    sys.stdout.write(json.dumps({"time": float(time), "entity": entity, "event": event, "payload": payload}) + "\n")


@dataclass(frozen=True)
class Pallet:
    pallet_id: int
    gen_time: float
    expiration_time: float


class LoadingQueue:
    """FIFO queue with active expiration."""

    def __init__(self, env: simpy.Environment):
        self.env = env
        self._q: Deque[Pallet] = deque()
        self._expired_total = 0
        # Event that fires when queue transitions from empty->non-empty
        self.nonempty_event = simpy.Event(env)

    def __len__(self) -> int:
        return len(self._q)

    def put(self, pallet: Pallet) -> None:
        was_empty = len(self._q) == 0
        self._q.append(pallet)
        emit(self.env.now, "queue", "pallet_queued", {"pallet_id": pallet.pallet_id, "queue_size": len(self._q)})
        if was_empty and not self.nonempty_event.triggered:
            self.nonempty_event.succeed()

    def get(self) -> Optional[Pallet]:
        if not self._q:
            return None
        return self._q.popleft()

    def _remove_by_id(self, pallet_id: int) -> bool:
        """Remove pallet by id if present. Returns True if removed."""
        for i, p in enumerate(self._q):
            if p.pallet_id == pallet_id:
                del self._q[i]
                return True
        return False

    def schedule_expiration(self, pallet: Pallet) -> None:
        """Start a process that expires this pallet if still in queue at deadline."""

        def _expire_proc() -> simpy.events.Event:
            # Wait until expiration time
            delay = max(0.0, pallet.expiration_time - self.env.now)
            yield self.env.timeout(delay)
            # Expire only if still in queue
            if self._remove_by_id(pallet.pallet_id):
                self._expired_total += 1
                emit(
                    self.env.now,
                    "queue",
                    "pallet_expired",
                    {"pallet_id": pallet.pallet_id, "total_expired": self._expired_total},
                )

        self.env.process(_expire_proc())

    def wait_for_nonempty(self) -> simpy.Event:
        if self._q:
            ev = simpy.Event(self.env)
            ev.succeed()
            return ev
        # reset event if already triggered
        if self.nonempty_event.triggered:
            self.nonempty_event = simpy.Event(self.env)
        return self.nonempty_event


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

    def run(self) -> simpy.events.Event:
        # Generate at t=0, t+interval, ...
        while True:
            pallet_id = self._next_id
            self._next_id += 1
            gen_time = float(self.env.now)
            expiration_time = gen_time + self.pallet_expiration_time
            pallet = Pallet(pallet_id=pallet_id, gen_time=gen_time, expiration_time=expiration_time)

            emit(self.env.now, "facility", "pallet_generated", {"pallet_id": pallet_id, "expiration_time": expiration_time})
            self.queue.put(pallet)
            self.queue.schedule_expiration(pallet)

            yield self.env.timeout(self.pallet_interval)


class Destination:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def delivered(self, pallet: Pallet, aircraft_id: int) -> None:
        latency = float(self.env.now - pallet.gen_time)
        emit(
            self.env.now,
            "destination",
            "pallet_delivered",
            {"pallet_id": pallet.pallet_id, "aircraft_id": aircraft_id, "latency": latency},
        )


class Aircraft:
    """Aircraft cycle. Capacity 1 pallet."""

    def __init__(
        self,
        env: simpy.Environment,
        aircraft_id: int,
        destination: Destination,
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
    ):
        self.env = env
        self.aircraft_id = int(aircraft_id)
        self.destination = destination
        self.flight_time = float(flight_time)
        self.unload_time = float(unload_time)
        self.return_time = float(return_time)
        self.maintenance_time = float(maintenance_time)

        self.state = "idle"
        self._assigned: Optional[Pallet] = None
        # Event used by coordinator to wait for idle transitions
        self.idle_event = simpy.Event(env)
        self.idle_event.succeed()  # initially idle

    def is_idle(self) -> bool:
        return self.state == "idle" and self._assigned is None

    def assign(self, pallet: Pallet) -> None:
        # Loading is instantaneous; depart at assignment time.
        self._assigned = pallet
        self.state = "in_flight"
        # consume idle_event
        if not self.idle_event.triggered:
            # should not happen; but keep safe
            self.idle_event.succeed()
        self.idle_event = simpy.Event(self.env)

        emit(self.env.now, "aircraft", "depart", {"aircraft_id": self.aircraft_id, "pallet_id": pallet.pallet_id})
        self.env.process(self._cycle())

    def _cycle(self) -> simpy.events.Event:
        pallet = self._assigned
        assert pallet is not None

        # Fly
        yield self.env.timeout(self.flight_time)

        # Unload
        self.state = "unloading"
        yield self.env.timeout(self.unload_time)
        self.destination.delivered(pallet, self.aircraft_id)

        # Return
        self.state = "returning"
        yield self.env.timeout(self.return_time)
        emit(self.env.now, "aircraft", "return", {"aircraft_id": self.aircraft_id})

        # Maintenance
        self.state = "maintenance"
        emit(self.env.now, "aircraft", "maintenance_start", {"aircraft_id": self.aircraft_id})
        yield self.env.timeout(self.maintenance_time)
        emit(self.env.now, "aircraft", "maintenance_end", {"aircraft_id": self.aircraft_id})

        # Back to idle
        self._assigned = None
        self.state = "idle"
        if not self.idle_event.triggered:
            self.idle_event.succeed()


class FleetCoordinator:
    """Assigns FIFO pallets to idle aircraft."""

    def __init__(self, env: simpy.Environment, queue: LoadingQueue, aircraft: Dict[int, Aircraft]):
        self.env = env
        self.queue = queue
        self.aircraft = aircraft

    def _any_idle(self) -> Optional[Aircraft]:
        for aid in sorted(self.aircraft.keys()):
            a = self.aircraft[aid]
            if a.is_idle():
                return a
        return None

    def run(self) -> simpy.events.Event:
        while True:
            # Wait until both: queue non-empty and some aircraft idle.
            while len(self.queue) == 0 or self._any_idle() is None:
                waits = []
                if len(self.queue) == 0:
                    waits.append(self.queue.wait_for_nonempty())
                idle_events = [a.idle_event for a in self.aircraft.values() if not a.is_idle()]
                if idle_events:
                    waits.append(simpy.AnyOf(self.env, idle_events))
                if not waits:
                    # queue non-empty but no idle events? should not happen
                    yield self.env.timeout(0)
                else:
                    yield simpy.AnyOf(self.env, waits)

            # Assign as many as possible at current time
            while len(self.queue) > 0:
                a = self._any_idle()
                if a is None:
                    break
                pallet = self.queue.get()
                if pallet is None:
                    break
                emit(self.env.now, "coordinator", "assignment_created", {"aircraft_id": a.aircraft_id, "pallet_id": pallet.pallet_id})
                a.assign(pallet)

            # allow other events at same time
            yield self.env.timeout(0)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Airfreight logistics DES simulation")
    p.add_argument("--duration", type=float, default=10000.0)
    p.add_argument("--num_aircraft", type=int, default=2)
    p.add_argument("--pallet_interval", type=float, default=25.0)
    p.add_argument("--pallet_expiration_time", type=float, default=150.0)
    p.add_argument("--flight_time", type=float, default=30.0)
    p.add_argument("--unload_time", type=float, default=2.0)
    p.add_argument("--return_time", type=float, default=30.0)
    p.add_argument("--maintenance_time", type=float, default=10.0)
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    _setup_logging()
    args = parse_args(argv)

    if args.num_aircraft < 1:
        print("--num_aircraft must be >= 1", file=sys.stderr)
        return 2
    if args.duration < 0:
        print("--duration must be >= 0", file=sys.stderr)
        return 2

    env = simpy.Environment()

    queue = LoadingQueue(env)
    destination = Destination(env)

    aircraft: Dict[int, Aircraft] = {
        i: Aircraft(
            env,
            aircraft_id=i,
            destination=destination,
            flight_time=args.flight_time,
            unload_time=args.unload_time,
            return_time=args.return_time,
            maintenance_time=args.maintenance_time,
        )
        for i in range(1, args.num_aircraft + 1)
    }

    facility = Facility(
        env,
        queue=queue,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
    )
    coordinator = FleetCoordinator(env, queue=queue, aircraft=aircraft)

    env.process(facility.run())
    env.process(coordinator.run())

    # Run purely in simulation time.
    env.run(until=float(args.duration))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
