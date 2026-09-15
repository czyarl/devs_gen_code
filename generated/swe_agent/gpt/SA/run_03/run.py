#!/usr/bin/env python3
"""Airfreight logistics DES simulation.

Entry point: python run.py

Stdout: JSONL event stream only.
Stderr: debug/logging.

Implements the scenario described in the PR: facility generates pallets, queue expires
pallets while waiting, coordinator assigns FIFO pallets to idle aircraft, and
aircraft execute a cyclic transport process.

Note: Uses simulation time only (SimPy DES). No wall-clock waiting.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import OrderedDict, deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional

import simpy


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )


def emit(time: float, entity: str, event: str, payload: dict) -> None:
    """Emit one JSONL event to stdout."""
    sys.stdout.write(
        json.dumps({"time": float(time), "entity": entity, "event": event, "payload": payload}) + "\n"
    )
    # Helpful when stdout is being consumed incrementally.
    sys.stdout.flush()


@dataclass(frozen=True)
class Pallet:
    pallet_id: int
    gen_time: float
    expiration_time: float


class LoadingQueue:
    """FIFO queue with active expirations."""

    def __init__(self, env: simpy.Environment):
        self.env = env
        self._items: "OrderedDict[int, Pallet]" = OrderedDict()
        self.total_expired = 0
        self._on_change = None

    def set_on_change(self, cb) -> None:
        self._on_change = cb

    def _notify_change(self) -> None:
        if self._on_change is not None:
            self._on_change()

    def __len__(self) -> int:
        return len(self._items)

    def put(self, pallet: Pallet) -> None:
        self._items[pallet.pallet_id] = pallet
        emit(
            self.env.now,
            "queue",
            "pallet_queued",
            {"pallet_id": pallet.pallet_id, "queue_size": len(self._items)},
        )
        # Schedule expiration watcher.
        self.env.process(self._expire_at_deadline(pallet.pallet_id, pallet.expiration_time))
        self._notify_change()

    def _is_expired_now(self, pallet: Pallet) -> bool:
        # Pallet expires exactly at expiration_time. Treat == as expired.
        return self.env.now >= pallet.expiration_time

    def pop_next(self) -> Optional[Pallet]:
        """Pop next non-expired pallet (FIFO). Returns None if none available."""
        while self._items:
            pid, pallet = next(iter(self._items.items()))
            if self._is_expired_now(pallet):
                # If still present at/after deadline, expire it now.
                del self._items[pid]
                self.total_expired += 1
                emit(
                    self.env.now,
                    "queue",
                    "pallet_expired",
                    {"pallet_id": pid, "total_expired": self.total_expired},
                )
                continue
            del self._items[pid]
            self._notify_change()
            return pallet
        return None

    def _expire_at_deadline(self, pallet_id: int, expiration_time: float):
        delay = max(0.0, expiration_time - self.env.now)
        yield self.env.timeout(delay)
        pallet = self._items.get(pallet_id)
        if pallet is None:
            return  # already assigned/expired
        # Expire immediately at deadline if still in queue.
        if self.env.now >= expiration_time:
            del self._items[pallet_id]
            self.total_expired += 1
            emit(
                self.env.now,
                "queue",
                "pallet_expired",
                {"pallet_id": pallet_id, "total_expired": self.total_expired},
            )
            self._notify_change()


class Destination:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def delivered(self, pallet: Pallet, aircraft_id: int) -> None:
        latency = self.env.now - pallet.gen_time
        emit(
            self.env.now,
            "destination",
            "pallet_delivered",
            {"pallet_id": pallet.pallet_id, "aircraft_id": aircraft_id, "latency": float(latency)},
        )


class Coordinator:
    def __init__(self, env: simpy.Environment, queue: LoadingQueue):
        self.env = env
        self.queue = queue
        self.aircraft_by_id: Dict[int, "Aircraft"] = {}
        self.available_aircraft: Deque[int] = deque()
        self._wakeup = env.event()

    def register_aircraft(self, aircraft: "Aircraft") -> None:
        self.aircraft_by_id[aircraft.aircraft_id] = aircraft

    def notify(self) -> None:
        # Wake up coordinator if sleeping.
        if not self._wakeup.triggered:
            self._wakeup.succeed()

    def aircraft_idle(self, aircraft_id: int) -> None:
        self.available_aircraft.append(aircraft_id)
        self.notify()

    def run(self):
        while True:
            # Create as many assignments as possible at this simulation time.
            while self.available_aircraft:
                pallet = self.queue.pop_next()
                if pallet is None:
                    break
                aircraft_id = self.available_aircraft.popleft()
                emit(
                    self.env.now,
                    "coordinator",
                    "assignment_created",
                    {"aircraft_id": aircraft_id, "pallet_id": pallet.pallet_id},
                )
                self.aircraft_by_id[aircraft_id].assign(pallet)

            # Sleep until notified about queue/aircraft changes.
            yield self._wakeup
            self._wakeup = self.env.event()


class Aircraft:
    def __init__(
        self,
        env: simpy.Environment,
        aircraft_id: int,
        coordinator: Coordinator,
        destination: Destination,
        *,
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
    ):
        self.env = env
        self.aircraft_id = aircraft_id
        self.coordinator = coordinator
        self.destination = destination

        self.flight_time = float(flight_time)
        self.unload_time = float(unload_time)
        self.return_time = float(return_time)
        self.maintenance_time = float(maintenance_time)

        self._assignment_event = env.event()
        self._assigned_pallet: Optional[Pallet] = None

    def assign(self, pallet: Pallet) -> None:
        self._assigned_pallet = pallet
        if not self._assignment_event.triggered:
            self._assignment_event.succeed()

    def run(self):
        # Initially idle.
        self.coordinator.aircraft_idle(self.aircraft_id)

        while True:
            # Wait for an assignment. Important: we must wait on the same event
            # that assign() will trigger.
            yield self._assignment_event
            self._assignment_event = self.env.event()

            pallet = self._assigned_pallet
            if pallet is None:
                self.coordinator.aircraft_idle(self.aircraft_id)
                continue

            # Loading is instantaneous -> depart at assignment time.
            emit(
                self.env.now,
                "aircraft",
                "depart",
                {"aircraft_id": self.aircraft_id, "pallet_id": pallet.pallet_id},
            )

            # Fly to destination.
            yield self.env.timeout(self.flight_time)
            # Unload.
            yield self.env.timeout(self.unload_time)
            # Delivery happens when unloading completes.
            self.destination.delivered(pallet, self.aircraft_id)

            # Return.
            yield self.env.timeout(self.return_time)
            emit(self.env.now, "aircraft", "return", {"aircraft_id": self.aircraft_id})

            # Maintenance.
            emit(self.env.now, "aircraft", "maintenance_start", {"aircraft_id": self.aircraft_id})
            yield self.env.timeout(self.maintenance_time)
            emit(self.env.now, "aircraft", "maintenance_end", {"aircraft_id": self.aircraft_id})

            self._assigned_pallet = None
            self.coordinator.aircraft_idle(self.aircraft_id)


class Facility:
    def __init__(
        self,
        env: simpy.Environment,
        queue: LoadingQueue,
        coordinator: Coordinator,
        *,
        pallet_interval: float,
        pallet_expiration_time: float,
    ):
        self.env = env
        self.queue = queue
        self.coordinator = coordinator
        self.pallet_interval = float(pallet_interval)
        self.pallet_expiration_time = float(pallet_expiration_time)
        self._next_id = 1

    def run(self):
        # Generate first pallet at t=0, then every pallet_interval.
        while True:
            pallet_id = self._next_id
            self._next_id += 1

            gen_time = float(self.env.now)
            expiration_time = gen_time + self.pallet_expiration_time

            emit(
                self.env.now,
                "facility",
                "pallet_generated",
                {"pallet_id": pallet_id, "expiration_time": float(expiration_time)},
            )

            self.queue.put(Pallet(pallet_id=pallet_id, gen_time=gen_time, expiration_time=expiration_time))
            self.coordinator.notify()

            yield self.env.timeout(self.pallet_interval)


def parse_args(argv=None) -> argparse.Namespace:
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
        p.error("--num_aircraft must be >= 1")
    if args.duration < 0:
        p.error("--duration must be >= 0")
    if args.pallet_interval <= 0:
        p.error("--pallet_interval must be > 0")
    if args.pallet_expiration_time < 0:
        p.error("--pallet_expiration_time must be >= 0")
    for name in ("flight_time", "unload_time", "return_time", "maintenance_time"):
        if getattr(args, name) < 0:
            p.error(f"--{name} must be >= 0")

    return args


def main(argv=None) -> int:
    _setup_logging()
    args = parse_args(argv)

    # All non-JSON output goes to stderr via logging.
    logging.info("Starting simulation")

    env = simpy.Environment()
    queue = LoadingQueue(env)
    coordinator = Coordinator(env, queue)
    queue.set_on_change(coordinator.notify)
    destination = Destination(env)

    for i in range(1, args.num_aircraft + 1):
        aircraft = Aircraft(
            env,
            i,
            coordinator,
            destination,
            flight_time=args.flight_time,
            unload_time=args.unload_time,
            return_time=args.return_time,
            maintenance_time=args.maintenance_time,
        )
        coordinator.register_aircraft(aircraft)
        env.process(aircraft.run())

    facility = Facility(
        env,
        queue,
        coordinator,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
    )
    env.process(facility.run())

    env.process(coordinator.run())

    duration = float(args.duration)
    if duration == 0.0:
        # SimPy's env.run(until=0) executes nothing; we still want to process all
        # events scheduled at t=0 (e.g., initial pallet generation/assignment).
        while env.peek() == 0:
            env.step()
    else:
        env.run(until=duration)

    logging.info("Simulation complete at t=%s", env.now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
