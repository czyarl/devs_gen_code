#!/usr/bin/env python3
"""Airfreight logistics DES simulation.

Entry point: python run.py

All required events are printed to stdout as JSONL. Any logs go to stderr.

Implements the PR scenario using a Discrete Event Simulation (DES) engine (simpy).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional

import simpy


# ----------------------- Logging (stderr only) -----------------------

LOG = logging.getLogger("sa_02")


class JsonlEmitter:
    """Emits JSONL events to stdout only."""

    def __init__(self, out_stream):
        self._out = out_stream

    def emit(self, *, time: float, entity: str, event: str, payload: Dict[str, Any]) -> None:
        obj = {"time": float(time), "entity": entity, "event": event, "payload": payload}
        self._out.write(json.dumps(obj) + "\n")


@dataclass
class Pallet:
    pallet_id: int
    gen_time: float
    expiration_time: float
    assigned: bool = False
    expired: bool = False


class LoadingQueue:
    """FIFO queue with active expiration.

    Expiration counts ONLY while the pallet is in the queue. Once assigned, it is safe.
    """

    def __init__(
        self,
        env: simpy.Environment,
        emit: JsonlEmitter,
        *,
        on_change: Optional[Callable[[], None]] = None,
    ):
        self.env = env
        self.emit = emit
        self._on_change = on_change

        self._fifo: Deque[int] = deque()  # pallet_ids in arrival order (may contain stale ids)
        self._pallets: Dict[int, Pallet] = {}  # active pallets (in queue)
        self._size: int = 0
        self._total_expired: int = 0

    @property
    def size(self) -> int:
        return self._size

    @property
    def total_expired(self) -> int:
        return self._total_expired

    def add(self, pallet: Pallet) -> None:
        self._fifo.append(pallet.pallet_id)
        self._pallets[pallet.pallet_id] = pallet
        self._size += 1

        self.emit.emit(
            time=self.env.now,
            entity="queue",
            event="pallet_queued",
            payload={"pallet_id": pallet.pallet_id, "queue_size": self._size},
        )

        # Schedule expiration
        self.env.process(self._expire_watcher(pallet.pallet_id, pallet.expiration_time))

        if self._on_change:
            self._on_change()

    def _expire_now_if_needed(self, pallet_id: int) -> bool:
        pallet = self._pallets.get(pallet_id)
        if pallet is None:
            return False
        if pallet.assigned or pallet.expired:
            return False
        if float(self.env.now) < float(pallet.expiration_time):
            return False

        pallet.expired = True
        self._pallets.pop(pallet_id, None)
        self._size -= 1
        self._total_expired += 1

        self.emit.emit(
            time=self.env.now,
            entity="queue",
            event="pallet_expired",
            payload={"pallet_id": pallet_id, "total_expired": self._total_expired},
        )
        return True

    def pop_next_for_assignment(self) -> Optional[Pallet]:
        """Return next FIFO pallet that is still valid; remove it from the queue."""
        while self._fifo:
            pid = self._fifo[0]

            # Ensure immediate expiration at boundary times.
            self._expire_now_if_needed(pid)

            pallet = self._pallets.get(pid)
            if pallet is None:
                self._fifo.popleft()  # stale
                continue

            self._fifo.popleft()
            pallet.assigned = True
            self._pallets.pop(pid, None)
            self._size -= 1
            return pallet

        return None

    def _expire_watcher(self, pallet_id: int, expiration_time: float):
        delay = max(0.0, float(expiration_time) - float(self.env.now))
        yield self.env.timeout(delay)
        self._expire_now_if_needed(pallet_id)
        if self._on_change:
            self._on_change()


class Aircraft:
    """Aircraft cyclic operation.

    Capacity is 1 pallet per trip.
    Loading time is 0s, so depart event occurs at assignment time.
    """

    def __init__(
        self,
        env: simpy.Environment,
        emit: JsonlEmitter,
        *,
        aircraft_id: int,
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
        on_idle: Optional[Callable[[], None]] = None,
    ):
        self.env = env
        self.emit = emit
        self.aircraft_id = int(aircraft_id)

        self.flight_time = float(flight_time)
        self.unload_time = float(unload_time)
        self.return_time = float(return_time)
        self.maintenance_time = float(maintenance_time)

        self._on_idle = on_idle
        self._inbox: simpy.Store[Pallet] = simpy.Store(env)

        self.idle: bool = True

    def assign(self, pallet: Pallet) -> None:
        self.idle = False
        self._inbox.put(pallet)

    def run(self):
        # start idle
        if self._on_idle:
            self._on_idle()

        while True:
            pallet: Pallet = yield self._inbox.get()

            # Depart immediately (load time = 0)
            self.emit.emit(
                time=self.env.now,
                entity="aircraft",
                event="depart",
                payload={"aircraft_id": self.aircraft_id, "pallet_id": pallet.pallet_id},
            )

            yield self.env.timeout(self.flight_time)
            yield self.env.timeout(self.unload_time)

            latency = float(self.env.now) - float(pallet.gen_time)
            self.emit.emit(
                time=self.env.now,
                entity="destination",
                event="pallet_delivered",
                payload={
                    "pallet_id": pallet.pallet_id,
                    "aircraft_id": self.aircraft_id,
                    "latency": float(latency),
                },
            )

            yield self.env.timeout(self.return_time)
            self.emit.emit(
                time=self.env.now,
                entity="aircraft",
                event="return",
                payload={"aircraft_id": self.aircraft_id},
            )

            self.emit.emit(
                time=self.env.now,
                entity="aircraft",
                event="maintenance_start",
                payload={"aircraft_id": self.aircraft_id},
            )
            yield self.env.timeout(self.maintenance_time)
            self.emit.emit(
                time=self.env.now,
                entity="aircraft",
                event="maintenance_end",
                payload={"aircraft_id": self.aircraft_id},
            )

            self.idle = True
            if self._on_idle:
                self._on_idle()


class FleetCoordinator:
    """Assign pallets to idle aircraft in FIFO order."""

    def __init__(
        self,
        env: simpy.Environment,
        emit: JsonlEmitter,
        queue: LoadingQueue,
        aircraft: List[Aircraft],
    ):
        self.env = env
        self.emit = emit
        self.queue = queue
        self.aircraft = aircraft
        self._wakeup = env.event()

    def notify(self) -> None:
        if not self._wakeup.triggered:
            self._wakeup.succeed()

    def _next_idle_aircraft(self) -> Optional[Aircraft]:
        for ac in self.aircraft:
            if ac.idle:
                return ac
        return None

    def run(self):
        while True:
            made_progress = False
            while True:
                ac = self._next_idle_aircraft()
                if ac is None:
                    break
                pallet = self.queue.pop_next_for_assignment()
                if pallet is None:
                    break

                self.emit.emit(
                    time=self.env.now,
                    entity="coordinator",
                    event="assignment_created",
                    payload={"aircraft_id": ac.aircraft_id, "pallet_id": pallet.pallet_id},
                )
                ac.assign(pallet)
                made_progress = True

            if made_progress:
                continue

            self._wakeup = self.env.event()
            yield self._wakeup


class Facility:
    """Generates pallets at a fixed interval starting at t=0."""

    def __init__(
        self,
        env: simpy.Environment,
        emit: JsonlEmitter,
        *,
        pallet_interval: float,
        pallet_expiration_time: float,
        queue: LoadingQueue,
        coordinator: FleetCoordinator,
    ):
        self.env = env
        self.emit = emit
        self.pallet_interval = float(pallet_interval)
        self.pallet_expiration_time = float(pallet_expiration_time)
        self.queue = queue
        self.coordinator = coordinator

        self._next_pallet_id = 1

    def run(self):
        while True:
            gen_time = float(self.env.now)
            pid = self._next_pallet_id
            self._next_pallet_id += 1

            expiration_time = gen_time + self.pallet_expiration_time
            self.emit.emit(
                time=self.env.now,
                entity="facility",
                event="pallet_generated",
                payload={"pallet_id": pid, "expiration_time": float(expiration_time)},
            )

            self.queue.add(Pallet(pallet_id=pid, gen_time=gen_time, expiration_time=expiration_time))
            self.coordinator.notify()

            yield self.env.timeout(self.pallet_interval)


def _nonneg_float(name: str, v: str) -> float:
    try:
        f = float(v)
    except Exception as e:  # pragma: no cover
        raise argparse.ArgumentTypeError(f"{name} must be a float") from e
    if f < 0:
        raise argparse.ArgumentTypeError(f"{name} must be >= 0")
    return f


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Airfreight logistics DES simulation")
    p.add_argument("--duration", type=lambda x: _nonneg_float("duration", x), default=10000.0)
    p.add_argument("--num_aircraft", type=int, default=2)
    p.add_argument("--pallet_interval", type=lambda x: _nonneg_float("pallet_interval", x), default=25.0)
    p.add_argument(
        "--pallet_expiration_time",
        type=lambda x: _nonneg_float("pallet_expiration_time", x),
        default=150.0,
    )
    p.add_argument("--flight_time", type=lambda x: _nonneg_float("flight_time", x), default=30.0)
    p.add_argument("--unload_time", type=lambda x: _nonneg_float("unload_time", x), default=2.0)
    p.add_argument("--return_time", type=lambda x: _nonneg_float("return_time", x), default=30.0)
    p.add_argument("--maintenance_time", type=lambda x: _nonneg_float("maintenance_time", x), default=10.0)

    ns = p.parse_args(argv)
    if ns.num_aircraft < 1:
        p.error("--num_aircraft must be >= 1")

    # Avoid an infinite number of events at t=0.
    if ns.pallet_interval <= 0:
        p.error("--pallet_interval must be > 0")

    return ns


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    env = simpy.Environment()
    emitter = JsonlEmitter(sys.stdout)

    aircraft_list: List[Aircraft] = []

    # Create coordinator after queue, but we need wakeup callbacks, so build in steps.
    coordinator = FleetCoordinator(env, emitter, None, aircraft_list)  # type: ignore[arg-type]

    def wake_coord() -> None:
        coordinator.notify()

    queue = LoadingQueue(env, emitter, on_change=wake_coord)
    coordinator.queue = queue

    for i in range(1, args.num_aircraft + 1):
        aircraft_list.append(
            Aircraft(
                env,
                emitter,
                aircraft_id=i,
                flight_time=args.flight_time,
                unload_time=args.unload_time,
                return_time=args.return_time,
                maintenance_time=args.maintenance_time,
                on_idle=wake_coord,
            )
        )

    facility = Facility(
        env,
        emitter,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
        queue=queue,
        coordinator=coordinator,
    )

    env.process(coordinator.run())
    for ac in aircraft_list:
        env.process(ac.run())
    env.process(facility.run())

    # Simulation time only (no real-time waits). Fast and deterministic.
    env.run(until=float(args.duration))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
