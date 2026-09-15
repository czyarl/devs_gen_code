#!/usr/bin/env python3
"""Airfreight logistics DES simulation.

Entry point: python run.py

Stdout: JSONL events only.
Stderr: logs/debug.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import deque
from dataclasses import dataclass

import simpy


def setup_logging() -> None:
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
    def __init__(self, env: simpy.Environment):
        self.env = env
        self._q: deque[Pallet] = deque()
        self._expired = 0
        self._changed = simpy.Event(env)  # triggered on enqueue/dequeue/expire

    def _trigger_changed(self) -> None:
        if not self._changed.triggered:
            self._changed.succeed()
        self._changed = simpy.Event(self.env)

    @property
    def changed(self) -> simpy.Event:
        return self._changed

    def __len__(self) -> int:
        return len(self._q)

    def put(self, pallet: Pallet) -> None:
        self._q.append(pallet)
        emit(self.env.now, "queue", "pallet_queued", {"pallet_id": pallet.pallet_id, "queue_size": len(self._q)})
        self._trigger_changed()

    def pop_fifo(self) -> Pallet | None:
        if not self._q:
            return None
        p = self._q.popleft()
        self._trigger_changed()
        return p

    def _expire_due(self) -> None:
        # Expire all pallets whose deadline has been reached (<= now)
        while self._q and self._q[0].expiration_time <= self.env.now:
            p = self._q.popleft()
            self._expired += 1
            emit(self.env.now, "queue", "pallet_expired", {"pallet_id": p.pallet_id, "total_expired": self._expired})
        # If anything changed, notify
        self._trigger_changed()

    def expiration_monitor(self):
        """Actively expire pallets exactly at their deadlines while they remain queued."""
        while True:
            if not self._q:
                # Wait until something arrives
                yield self.changed
                continue

            # Ensure any already-due expirations are processed
            if self._q and self._q[0].expiration_time <= self.env.now:
                self._expire_due()
                continue

            next_deadline = self._q[0].expiration_time
            # Wait until either the next deadline or a queue change (new earlier deadline or dequeue)
            deadline_evt = self.env.timeout(next_deadline - self.env.now)
            changed_evt = self.changed
            res = yield deadline_evt | changed_evt
            if deadline_evt in res:
                # time reached next_deadline
                self._expire_due()


class Aircraft:
    def __init__(
        self,
        env: simpy.Environment,
        aircraft_id: int,
        coordinator: "FleetCoordinator",
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
    ):
        self.env = env
        self.aircraft_id = aircraft_id
        self.coordinator = coordinator
        self.flight_time = float(flight_time)
        self.unload_time = float(unload_time)
        self.return_time = float(return_time)
        self.maintenance_time = float(maintenance_time)

        self.idle = True
        self._assigned: Pallet | None = None
        self._assign_evt = simpy.Event(env)

        self.process = env.process(self._run())

    def assign(self, pallet: Pallet) -> None:
        self._assigned = pallet
        self.idle = False
        if not self._assign_evt.triggered:
            self._assign_evt.succeed(pallet)

    def _reset_assign_evt(self) -> None:
        self._assign_evt = simpy.Event(self.env)

    def _run(self):
        while True:
            # Wait idle until assigned
            if self._assigned is None:
                self.idle = True
                self.coordinator.notify_aircraft_idle(self)
                yield self._assign_evt
                self._reset_assign_evt()

            pallet = self._assigned
            assert pallet is not None

            # Load is instantaneous; depart at assignment time
            emit(self.env.now, "aircraft", "depart", {"aircraft_id": self.aircraft_id, "pallet_id": pallet.pallet_id})

            # Fly to destination
            yield self.env.timeout(self.flight_time)

            # Unload
            yield self.env.timeout(self.unload_time)
            latency = self.env.now - pallet.generation_time
            emit(
                self.env.now,
                "destination",
                "pallet_delivered",
                {"pallet_id": pallet.pallet_id, "aircraft_id": self.aircraft_id, "latency": float(latency)},
            )

            # Return
            yield self.env.timeout(self.return_time)
            emit(self.env.now, "aircraft", "return", {"aircraft_id": self.aircraft_id})

            # Maintenance
            emit(self.env.now, "aircraft", "maintenance_start", {"aircraft_id": self.aircraft_id})
            yield self.env.timeout(self.maintenance_time)
            emit(self.env.now, "aircraft", "maintenance_end", {"aircraft_id": self.aircraft_id})

            # Cycle complete
            self._assigned = None


class FleetCoordinator:
    def __init__(self, env: simpy.Environment, queue: LoadingQueue):
        self.env = env
        self.queue = queue
        self.aircraft: list[Aircraft] = []
        self._wakeup = simpy.Event(env)

    def add_aircraft(self, ac: Aircraft) -> None:
        self.aircraft.append(ac)

    def _trigger(self) -> None:
        if not self._wakeup.triggered:
            self._wakeup.succeed()
        self._wakeup = simpy.Event(self.env)

    def notify_aircraft_idle(self, _ac: Aircraft) -> None:
        self._trigger()

    def notify_queue_changed(self) -> None:
        self._trigger()

    def _find_idle_aircraft(self) -> Aircraft | None:
        for ac in self.aircraft:
            if ac.idle and ac._assigned is None:
                return ac
        return None

    def run(self):
        while True:
            # Try to assign as much as possible at current time
            made_assignment = False
            while len(self.queue) > 0:
                ac = self._find_idle_aircraft()
                if ac is None:
                    break
                pallet = self.queue.pop_fifo()
                if pallet is None:
                    break
                emit(
                    self.env.now,
                    "coordinator",
                    "assignment_created",
                    {"aircraft_id": ac.aircraft_id, "pallet_id": pallet.pallet_id},
                )
                ac.assign(pallet)
                made_assignment = True

            if made_assignment:
                # loop again in case multiple idle aircraft exist
                continue

            # Wait for either queue change or aircraft idle notification
            queue_evt = self.queue.changed
            wake_evt = self._wakeup
            yield queue_evt | wake_evt


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
            pallet_id = self._next_id
            self._next_id += 1
            gen_time = float(self.env.now)
            exp_time = gen_time + self.pallet_expiration_time
            pallet = Pallet(pallet_id=pallet_id, generation_time=gen_time, expiration_time=exp_time)
            emit(self.env.now, "facility", "pallet_generated", {"pallet_id": pallet_id, "expiration_time": float(exp_time)})
            self.queue.put(pallet)
            yield self.env.timeout(self.pallet_interval)


def parse_args(argv: list[str]) -> argparse.Namespace:
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


def main(argv: list[str]) -> int:
    setup_logging()
    args = parse_args(argv)

    if args.num_aircraft < 1:
        raise SystemExit("--num_aircraft must be >= 1")
    if args.duration < 0:
        raise SystemExit("--duration must be >= 0")

    env = simpy.Environment()

    queue = LoadingQueue(env)
    coordinator = FleetCoordinator(env, queue)

    # Processes
    env.process(queue.expiration_monitor())

    facility = Facility(env, queue, args.pallet_interval, args.pallet_expiration_time)
    env.process(facility.run())

    for i in range(1, args.num_aircraft + 1):
        ac = Aircraft(
            env,
            aircraft_id=i,
            coordinator=coordinator,
            flight_time=args.flight_time,
            unload_time=args.unload_time,
            return_time=args.return_time,
            maintenance_time=args.maintenance_time,
        )
        coordinator.add_aircraft(ac)

    env.process(coordinator.run())

    # Ensure coordinator wakes up on queue changes
    def coordinator_queue_bridge():
        while True:
            yield queue.changed
            coordinator.notify_queue_changed()

    env.process(coordinator_queue_bridge())

    env.run(until=float(args.duration))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
