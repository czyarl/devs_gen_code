#!/usr/bin/env python3
"""Airfreight logistics DES simulation.

Entry point: python run.py

Stdout: JSONL events only.
Stderr: logs/debug.

Implements:
- Facility generating pallets periodically
- Loading queue with active expiration
- Fleet coordinator assigning FIFO pallets to idle aircraft
- Aircraft cycle: depart -> fly -> unload(deliver) -> return -> maintenance -> idle

Uses simpy (DES). No real-time waiting.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, List

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
    generation_time: float
    expiration_time: float


class LoadingQueue:
    """FIFO queue with active expiration."""

    def __init__(self, env: simpy.Environment):
        self.env = env
        self._q: Deque[Pallet] = deque()
        self._expired_total = 0
        # Notifies coordinator when queue becomes non-empty.
        self.changed = simpy.Event(env)

    def __len__(self) -> int:
        return len(self._q)

    def put(self, pallet: Pallet) -> None:
        self._q.append(pallet)
        emit(self.env.now, "queue", "pallet_queued", {"pallet_id": pallet.pallet_id, "queue_size": len(self._q)})
        # Wake any waiters.
        if not self.changed.triggered:
            self.changed.succeed()
        self.changed = simpy.Event(self.env)

    def get(self) -> Optional[Pallet]:
        if not self._q:
            return None
        return self._q.popleft()

    def peek(self) -> Optional[Pallet]:
        return self._q[0] if self._q else None

    def expire_due(self) -> None:
        """Expire all pallets whose expiration_time <= now."""
        now = self.env.now
        changed = False
        while self._q and self._q[0].expiration_time <= now + 1e-12:
            p = self._q.popleft()
            self._expired_total += 1
            emit(now, "queue", "pallet_expired", {"pallet_id": p.pallet_id, "total_expired": self._expired_total})
            changed = True
        if changed:
            if not self.changed.triggered:
                self.changed.succeed()
            self.changed = simpy.Event(self.env)

    def next_expiration_time(self) -> Optional[float]:
        return self._q[0].expiration_time if self._q else None


class Aircraft:
    def __init__(
        self,
        env: simpy.Environment,
        aircraft_id: int,
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
        gen_times: Dict[int, float],
    ):
        self.env = env
        self.aircraft_id = aircraft_id
        self.flight_time = float(flight_time)
        self.unload_time = float(unload_time)
        self.return_time = float(return_time)
        self.maintenance_time = float(maintenance_time)
        self._gen_times = gen_times

        self.idle = True
        self._assignment: simpy.Store = simpy.Store(env, capacity=1)
        # Notifies coordinator when aircraft becomes idle.
        self.became_idle = simpy.Event(env)

        self.process = env.process(self._run())

    def assign(self, pallet: Pallet) -> None:
        # Coordinator ensures idle before assigning.
        self.idle = False
        self._assignment.put(pallet)

    def _signal_idle(self) -> None:
        if not self.became_idle.triggered:
            self.became_idle.succeed()
        self.became_idle = simpy.Event(self.env)

    def _run(self):
        while True:
            pallet: Pallet = yield self._assignment.get()

            # Load is instantaneous; depart at assignment time.
            emit(self.env.now, "aircraft", "depart", {"aircraft_id": self.aircraft_id, "pallet_id": pallet.pallet_id})

            # Fly to destination.
            yield self.env.timeout(self.flight_time)

            # Unload; delivery at unload completion.
            yield self.env.timeout(self.unload_time)
            gen_t = self._gen_times.get(pallet.pallet_id, pallet.generation_time)
            latency = float(self.env.now - gen_t)
            emit(
                self.env.now,
                "destination",
                "pallet_delivered",
                {"pallet_id": pallet.pallet_id, "aircraft_id": self.aircraft_id, "latency": latency},
            )

            # Return flight.
            yield self.env.timeout(self.return_time)
            emit(self.env.now, "aircraft", "return", {"aircraft_id": self.aircraft_id})

            # Maintenance.
            emit(self.env.now, "aircraft", "maintenance_start", {"aircraft_id": self.aircraft_id})
            yield self.env.timeout(self.maintenance_time)
            emit(self.env.now, "aircraft", "maintenance_end", {"aircraft_id": self.aircraft_id})

            # Back to idle.
            self.idle = True
            self._signal_idle()


class Facility:
    def __init__(
        self,
        env: simpy.Environment,
        queue: LoadingQueue,
        pallet_interval: float,
        pallet_expiration_time: float,
        gen_times: Dict[int, float],
    ):
        self.env = env
        self.queue = queue
        self.pallet_interval = float(pallet_interval)
        self.pallet_expiration_time = float(pallet_expiration_time)
        self._next_id = 1
        self._gen_times = gen_times

        self.process = env.process(self._run())

    def _run(self):
        # Generate at t=0, t+interval, ...
        while True:
            pid = self._next_id
            self._next_id += 1
            gen_t = float(self.env.now)
            exp_t = gen_t + self.pallet_expiration_time
            self._gen_times[pid] = gen_t

            emit(gen_t, "facility", "pallet_generated", {"pallet_id": pid, "expiration_time": float(exp_t)})
            self.queue.put(Pallet(pallet_id=pid, generation_time=gen_t, expiration_time=float(exp_t)))

            yield self.env.timeout(self.pallet_interval)


class Coordinator:
    def __init__(self, env: simpy.Environment, queue: LoadingQueue, aircraft: List[Aircraft]):
        self.env = env
        self.queue = queue
        self.aircraft = aircraft
        self.process = env.process(self._run())

    def _idle_aircraft(self) -> Optional[Aircraft]:
        for a in self.aircraft:
            if a.idle:
                return a
        return None

    def _run(self):
        while True:
            # Ensure expirations are processed before any assignment at this time.
            self.queue.expire_due()

            idle = self._idle_aircraft()
            if idle is not None and len(self.queue) > 0:
                pallet = self.queue.get()
                if pallet is not None:
                    emit(self.env.now, "coordinator", "assignment_created", {"aircraft_id": idle.aircraft_id, "pallet_id": pallet.pallet_id})
                    idle.assign(pallet)
                    # Loop again at same sim time to possibly assign more.
                    continue

            # Wait for next relevant event: queue change, aircraft idle, or next expiration.
            events = []
            events.append(self.queue.changed)
            for a in self.aircraft:
                events.append(a.became_idle)

            next_exp = self.queue.next_expiration_time()
            if next_exp is not None and next_exp > self.env.now:
                events.append(self.env.timeout(next_exp - self.env.now))
            elif next_exp is not None and next_exp <= self.env.now:
                # Expiration due now; loop.
                continue

            yield simpy.AnyOf(self.env, events)


def parse_args(argv: Optional[list] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Airfreight logistics DES simulation")
    p.add_argument("--duration", type=float, default=10000.0)
    p.add_argument("--num_aircraft", type=int, default=2)
    p.add_argument("--pallet_interval", type=float, default=25.0)
    p.add_argument("--pallet_expiration_time", type=float, default=150.0)
    p.add_argument("--flight_time", type=float, default=30.0)
    p.add_argument("--unload_time", type=float, default=2.0)
    p.add_argument("--return_time", type=float, default=30.0)
    p.add_argument("--maintenance_time", type=float, default=10.0)
    args = p.parse_args(argv)

    if args.num_aircraft < 1:
        raise SystemExit("--num_aircraft must be >= 1")
    if args.duration < 0:
        raise SystemExit("--duration must be >= 0")
    return args


def main(argv: Optional[list] = None) -> int:
    _setup_logging()
    args = parse_args(argv)

    # DES environment (simulation time only).
    env = simpy.Environment()

    gen_times: Dict[int, float] = {}
    queue = LoadingQueue(env)
    facility = Facility(
        env,
        queue=queue,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
        gen_times=gen_times,
    )
    _ = facility  # silence linters

    aircraft = [
        Aircraft(
            env,
            aircraft_id=i + 1,
            flight_time=args.flight_time,
            unload_time=args.unload_time,
            return_time=args.return_time,
            maintenance_time=args.maintenance_time,
            gen_times=gen_times,
        )
        for i in range(args.num_aircraft)
    ]

    _ = Coordinator(env, queue=queue, aircraft=aircraft)

    # Run until duration.
    env.run(until=float(args.duration))

    # Process any expirations exactly at end time.
    queue.expire_due()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
