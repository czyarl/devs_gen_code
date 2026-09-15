#!/usr/bin/env python3
"""Airfreight logistics DES simulation (SimPy).

Stdout: JSONL event stream only.
Stderr: logs/debug.

Entry point: python run.py
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import deque
from typing import Any, Deque, Dict, Optional

import simpy
from simpy.events import Event, URGENT, NORMAL


class UrgentTimeout(simpy.events.Timeout):
    """A SimPy Timeout scheduled with URGENT priority.

    SimPy's built-in Timeout uses NORMAL priority. We need URGENT events so that
    pallet expiration at time t is processed before any NORMAL events at time t
    (e.g., coordinator assignments).
    """

    def __init__(self, env: simpy.Environment, delay: float, value: Optional[Any] = None):
        if delay < 0:
            raise ValueError(f"Negative delay {delay}")
        # Inline the initialization that SimPy's Timeout does, but schedule URGENT.
        self.env = env
        self.callbacks = []
        self._value = value
        self._delay = delay
        self._ok = True
        env.schedule(self, URGENT, delay)


class EventLogger:
    def __init__(self, out_stream):
        self._out = out_stream

    def emit(self, time_now: float, entity: str, event: str, payload: Dict[str, Any]) -> None:
        obj = {
            "time": float(time_now),
            "entity": entity,
            "event": event,
            "payload": payload,
        }
        self._out.write(json.dumps(obj, separators=(",", ":")) + "\n")


class Destination:
    def __init__(self, logger: EventLogger, pallet_registry: Dict[int, Dict[str, Any]]):
        self.logger = logger
        self.pallet_registry = pallet_registry

    def deliver(self, time_now: float, pallet_id: int, aircraft_id: int) -> None:
        gen_time = float(self.pallet_registry[pallet_id]["gen_time"])
        latency = float(time_now) - gen_time
        self.logger.emit(
            time_now=time_now,
            entity="destination",
            event="pallet_delivered",
            payload={
                "pallet_id": int(pallet_id),
                "aircraft_id": int(aircraft_id),
                "latency": float(latency),
            },
        )


class LoadingQueue:
    def __init__(self, env: simpy.Environment, logger: EventLogger, on_put=None):
        self.env = env
        self.logger = logger
        self._on_put = on_put  # optional callback to notify coordinator

        self._q: Deque[int] = deque()  # pallet_ids FIFO
        self._queued: Dict[int, bool] = {}  # pallet_id -> still queued?
        self._not_empty: Event = env.event()
        self.total_expired = 0

    def size(self) -> int:
        return len(self._q)

    def put(self, pallet_id: int, expiration_time: float) -> None:
        self._q.append(pallet_id)
        self._queued[pallet_id] = True
        self.logger.emit(
            time_now=self.env.now,
            entity="queue",
            event="pallet_queued",
            payload={"pallet_id": int(pallet_id), "queue_size": int(len(self._q))},
        )

        # Wake any waiters.
        if not self._not_empty.triggered:
            self._not_empty.succeed()

        # Notify coordinator (if provided) so it can attempt assignment.
        if self._on_put is not None:
            try:
                self._on_put()
            except Exception:
                # Keep simulation robust; avoid printing to stdout.
                logging.getLogger("airfreight").exception("on_put callback failed")

        # Schedule expiration.
        self.env.process(self._expire_at(pallet_id, float(expiration_time)))

    def _remove_from_deque(self, pallet_id: int) -> bool:
        """Remove pallet_id from deque if present. Return True if removed."""
        try:
            self._q.remove(pallet_id)
            return True
        except ValueError:
            return False

    def pop_fifo(self) -> int:
        pallet_id = self._q.popleft()
        self._queued[pallet_id] = False
        return pallet_id

    def mark_assigned_if_queued(self, pallet_id: int) -> bool:
        """Mark pallet as no longer queued (assigned). Returns True if it was queued."""
        was_queued = bool(self._queued.get(pallet_id, False))
        self._queued[pallet_id] = False
        return was_queued

    def when_non_empty(self) -> Event:
        if self._q:
            e = self.env.event()
            e.succeed()
            return e
        # Replace with a fresh event (previous may already be triggered).
        if self._not_empty.triggered:
            self._not_empty = self.env.event()
        return self._not_empty

    def _expire_at(self, pallet_id: int, expiration_time: float):
        # Urgent so it preempts NORMAL events at same sim time.
        delay = expiration_time - float(self.env.now)
        if delay < 0:
            delay = 0.0
        yield UrgentTimeout(self.env, delay)

        # If still in queue at deadline, discard immediately.
        if bool(self._queued.get(pallet_id, False)):
            removed = self._remove_from_deque(pallet_id)
            self._queued[pallet_id] = False
            if removed:
                self.total_expired += 1
                self.logger.emit(
                    time_now=self.env.now,
                    entity="queue",
                    event="pallet_expired",
                    payload={"pallet_id": int(pallet_id), "total_expired": int(self.total_expired)},
                )


class FleetCoordinator:
    def __init__(self, env: simpy.Environment, logger: EventLogger, queue: Optional[LoadingQueue] = None):
        self.env = env
        self.logger = logger
        self.queue: Optional[LoadingQueue] = queue

        self._idle_aircraft: Deque["Aircraft"] = deque()
        self._wakeup: Event = env.event()

    def wakeup(self) -> None:
        if not self._wakeup.triggered:
            self._wakeup.succeed()

    def aircraft_idle(self, aircraft: "Aircraft") -> None:
        self._idle_aircraft.append(aircraft)
        self.wakeup()

    def run(self):
        # Start immediately.
        self.wakeup()
        while True:
            # Assign while possible.
            if self.queue is None:
                # Not wired yet (should not happen in normal runs).
                self._wakeup = self.env.event()
                yield self._wakeup
                continue

            while self.queue.size() > 0 and self._idle_aircraft:
                pallet_id = self.queue.pop_fifo()
                aircraft = self._idle_aircraft.popleft()

                self.logger.emit(
                    time_now=self.env.now,
                    entity="coordinator",
                    event="assignment_created",
                    payload={"aircraft_id": int(aircraft.aircraft_id), "pallet_id": int(pallet_id)},
                )
                aircraft.assign(pallet_id)

            # Sleep until something changes.
            self._wakeup = self.env.event()
            yield self._wakeup


class Aircraft:
    def __init__(
        self,
        env: simpy.Environment,
        logger: EventLogger,
        coordinator: FleetCoordinator,
        destination: Destination,
        *,
        aircraft_id: int,
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
    ):
        self.env = env
        self.logger = logger
        self.coordinator = coordinator
        self.destination = destination

        self.aircraft_id = int(aircraft_id)
        self.flight_time = float(flight_time)
        self.unload_time = float(unload_time)
        self.return_time = float(return_time)
        self.maintenance_time = float(maintenance_time)

        self._assignment: Event = env.event()
        self._current_pallet: Optional[int] = None

    def assign(self, pallet_id: int) -> None:
        self._current_pallet = int(pallet_id)
        if not self._assignment.triggered:
            self._assignment.succeed(self._current_pallet)

    def run(self):
        # Initially idle at the facility.
        self.coordinator.aircraft_idle(self)

        while True:
            pallet_id = yield self._assignment
            self._assignment = self.env.event()

            # Load is instantaneous; depart immediately at assignment_time.
            self.logger.emit(
                time_now=self.env.now,
                entity="aircraft",
                event="depart",
                payload={"aircraft_id": int(self.aircraft_id), "pallet_id": int(pallet_id)},
            )

            # Fly to destination.
            yield self.env.timeout(self.flight_time)

            # Unload.
            yield self.env.timeout(self.unload_time)
            self.destination.deliver(time_now=self.env.now, pallet_id=int(pallet_id), aircraft_id=self.aircraft_id)

            # Return flight.
            yield self.env.timeout(self.return_time)
            self.logger.emit(
                time_now=self.env.now,
                entity="aircraft",
                event="return",
                payload={"aircraft_id": int(self.aircraft_id)},
            )

            # Maintenance.
            self.logger.emit(
                time_now=self.env.now,
                entity="aircraft",
                event="maintenance_start",
                payload={"aircraft_id": int(self.aircraft_id)},
            )
            yield self.env.timeout(self.maintenance_time)
            self.logger.emit(
                time_now=self.env.now,
                entity="aircraft",
                event="maintenance_end",
                payload={"aircraft_id": int(self.aircraft_id)},
            )

            # Back to idle.
            self.coordinator.aircraft_idle(self)


class Facility:
    def __init__(
        self,
        env: simpy.Environment,
        logger: EventLogger,
        queue: LoadingQueue,
        pallet_registry: Dict[int, Dict[str, Any]],
        *,
        pallet_interval: float,
        pallet_expiration_time: float,
    ):
        self.env = env
        self.logger = logger
        self.queue = queue
        self.pallet_registry = pallet_registry

        self.pallet_interval = float(pallet_interval)
        self.pallet_expiration_time = float(pallet_expiration_time)
        self._next_id = 1

    def run(self, total_duration: float):
        while True:
            now = float(self.env.now)
            if now > float(total_duration):
                return

            pallet_id = self._next_id
            self._next_id += 1

            expiration_time = now + self.pallet_expiration_time
            self.pallet_registry[pallet_id] = {
                "gen_time": now,
                "expiration_time": expiration_time,
            }

            self.logger.emit(
                time_now=now,
                entity="facility",
                event="pallet_generated",
                payload={"pallet_id": int(pallet_id), "expiration_time": float(expiration_time)},
            )
            self.queue.put(pallet_id=pallet_id, expiration_time=expiration_time)

            # Next pallet.
            yield self.env.timeout(self.pallet_interval)


def _pos_float(x: str) -> float:
    v = float(x)
    if v <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return v


def _nonneg_float(x: str) -> float:
    v = float(x)
    if v < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return v


def _int_ge_1(x: str) -> int:
    v = int(x)
    if v < 1:
        raise argparse.ArgumentTypeError("must be >= 1")
    return v


def parse_args(argv):
    p = argparse.ArgumentParser(description="Airfreight logistics DES simulation")
    p.add_argument("--duration", type=_nonneg_float, default=10000.0)
    p.add_argument("--num_aircraft", type=_int_ge_1, default=2)
    p.add_argument("--pallet_interval", type=_pos_float, default=25.0)
    p.add_argument("--pallet_expiration_time", type=_nonneg_float, default=150.0)
    p.add_argument("--flight_time", type=_nonneg_float, default=30.0)
    p.add_argument("--unload_time", type=_nonneg_float, default=2.0)
    p.add_argument("--return_time", type=_nonneg_float, default=30.0)
    p.add_argument("--maintenance_time", type=_nonneg_float, default=10.0)
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)

    # Keep stderr quiet by default; stdout must remain JSONL-only.
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.ERROR,
        format="%(levelname)s:%(message)s",
    )

    env = simpy.Environment()
    evlog = EventLogger(sys.stdout)

    pallet_registry: Dict[int, Dict[str, Any]] = {}

    coordinator = FleetCoordinator(env, evlog)
    queue = LoadingQueue(env, evlog, on_put=coordinator.wakeup)
    coordinator.queue = queue
    destination = Destination(evlog, pallet_registry)

    # Start coordinator.
    env.process(coordinator.run())

    # Create aircraft.
    for i in range(1, int(args.num_aircraft) + 1):
        ac = Aircraft(
            env,
            evlog,
            coordinator,
            destination,
            aircraft_id=i,
            flight_time=args.flight_time,
            unload_time=args.unload_time,
            return_time=args.return_time,
            maintenance_time=args.maintenance_time,
        )
        env.process(ac.run())

    # Facility (cargo source).
    facility = Facility(
        env,
        evlog,
        queue,
        pallet_registry,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
    )
    env.process(facility.run(total_duration=args.duration))

    # SimPy's env.run(until=t) does not process events at exactly t.
    # Run to just beyond duration so events at time==duration are included.
    until = float(args.duration) + 1e-9

    env.run(until=until)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
