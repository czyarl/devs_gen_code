#!/usr/bin/env python3
"""Airfreight logistics DES simulation.

Stdout: JSONL event stream only.
Stderr: logs/debug.
"""

import argparse
import json
import logging
import sys
from collections import deque

import simpy


def _make_logger() -> logging.Logger:
    logger = logging.getLogger("airfreight")


def _fmt_time(t):
    # Avoid negative zero and keep JSON stable.
    x = float(t)
    return 0.0 if abs(x) < 1e-12 else x

    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
    logger.handlers[:] = [handler]
    logger.propagate = False
    return logger


LOGGER = _make_logger()


class JsonlEmitter:
    def __init__(self):
        self._out = sys.stdout

    def emit(self, *, time, entity, event, payload):
        self._out.write(
            json.dumps({"time": float(time), "entity": str(entity), "event": str(event), "payload": payload}) + "\n"
        )


class Pallet:
    def __init__(self, pallet_id, generation_time, expiration_time):
        self.pallet_id = int(pallet_id)
        self.generation_time = float(generation_time)
        self.expiration_time = float(expiration_time)


class PalletRegistry:
    def __init__(self):
        self._pallets = {}

    def add(self, pallet):
        self._pallets[pallet.pallet_id] = pallet

    def get(self, pallet_id):
        return self._pallets[int(pallet_id)]


class LoadingQueue:
    """FIFO queue with expirations."""

    def __init__(self, *, emitter):
        self._emitter = emitter
        self._fifo = deque()
        self._status = {}  # pallet_id -> queued|assigned|expired
        self.active_size = 0
        self.total_expired = 0

    def enqueue(self, *, now, pallet_id):
        self._fifo.append(int(pallet_id))
        self._status[int(pallet_id)] = "queued"
        self.active_size += 1
        self._emitter.emit(
            time=now,
            entity="queue",
            event="pallet_queued",
            payload={"pallet_id": int(pallet_id), "queue_size": int(self.active_size)},
        )

    def mark_assigned(self, *, now, pallet_id):
        pallet_id = int(pallet_id)
        if self._status.get(pallet_id) != "queued":
            return
        self._status[pallet_id] = "assigned"
        self.active_size -= 1

    def expire(self, *, now, pallet_id):
        pallet_id = int(pallet_id)
        if self._status.get(pallet_id) != "queued":
            return
        self._status[pallet_id] = "expired"
        self.active_size -= 1
        self.total_expired += 1
        self._emitter.emit(
            time=now,
            entity="queue",
            event="pallet_expired",
            payload={"pallet_id": pallet_id, "total_expired": int(self.total_expired)},
        )

    def pop_next(self, *, now, registry):
        now = float(now)
        while self._fifo:
            pallet_id = int(self._fifo.popleft())
            if self._status.get(pallet_id) != "queued":
                continue
            pallet = registry.get(pallet_id)
            if pallet.expiration_time <= now:
                self.expire(now=now, pallet_id=pallet_id)
                continue
            return pallet_id
        return None


class Coordinator:
    def __init__(self, *, env, emitter, queue, registry):
        self._env = env
        self._emitter = emitter
        self._queue = queue
        self._registry = registry
        self._idle_aircraft = deque()

    def register_idle(self, aircraft):
        self._idle_aircraft.append(aircraft)
        self.try_assign()

    def notify_pallet_arrived(self):
        self.try_assign()

    def notify_pallet_expired(self):
        self.try_assign()

    def try_assign(self):
        now = float(self._env.now)
        while self._queue.active_size > 0 and self._idle_aircraft:
            pallet_id = self._queue.pop_next(now=now, registry=self._registry)
            if pallet_id is None:
                return

            aircraft = self._idle_aircraft.popleft()
            self._queue.mark_assigned(now=now, pallet_id=pallet_id)
            self._emitter.emit(
                time=now,
                entity="coordinator",
                event="assignment_created",
                payload={"aircraft_id": int(aircraft.aircraft_id), "pallet_id": int(pallet_id)},
            )
            aircraft.inbox.put(int(pallet_id))


class Facility:
    def __init__(
        self,
        *,
        env,
        emitter,
        registry,
        queue,
        coordinator,
        pallet_interval,
        pallet_expiration_time,
    ):
        self._env = env
        self._emitter = emitter
        self._registry = registry
        self._queue = queue
        self._coordinator = coordinator
        self._pallet_interval = float(pallet_interval)
        self._pallet_expiration_time = float(pallet_expiration_time)
        self._next_pallet_id = 1

    def start(self):
        self._env.process(self._run())

    def _schedule_expiration(self, pallet_id, expiration_time):
        def _expire():
            now = float(self._env.now)
            self._queue.expire(now=now, pallet_id=pallet_id)
            self._coordinator.notify_pallet_expired()

        self._env.process(self._expire_process(expiration_time, _expire))

    def _expire_process(self, expiration_time, fn):
        delay = max(0.0, float(expiration_time) - float(self._env.now))
        yield self._env.timeout(delay)
        fn()

    def _generate_one(self):
        now = float(self._env.now)
        pallet_id = int(self._next_pallet_id)
        self._next_pallet_id += 1

        expiration_time = now + self._pallet_expiration_time
        pallet = Pallet(pallet_id=pallet_id, generation_time=now, expiration_time=expiration_time)
        self._registry.add(pallet)

        self._emitter.emit(
            time=now,
            entity="facility",
            event="pallet_generated",
            payload={"pallet_id": pallet_id, "expiration_time": float(expiration_time)},
        )

        self._queue.enqueue(now=now, pallet_id=pallet_id)
        self._schedule_expiration(pallet_id, expiration_time)
        self._coordinator.notify_pallet_arrived()

    def _run(self):
        self._generate_one()
        while True:
            yield self._env.timeout(self._pallet_interval)
            self._generate_one()


class Aircraft:
    def __init__(
        self,
        *,
        env,
        emitter,
        registry,
        coordinator,
        aircraft_id,
        flight_time,
        unload_time,
        return_time,
        maintenance_time,
    ):
        self._env = env
        self._emitter = emitter
        self._registry = registry
        self._coordinator = coordinator
        self.aircraft_id = int(aircraft_id)

        self._flight_time = float(flight_time)
        self._unload_time = float(unload_time)
        self._return_time = float(return_time)
        self._maintenance_time = float(maintenance_time)

        self.inbox = simpy.Store(env, capacity=1)

    def start(self):
        self._env.process(self._run())
        self._coordinator.register_idle(self)

    def _run(self):
        while True:
            pallet_id = yield self.inbox.get()
            now = float(self._env.now)
            self._emitter.emit(
                time=now,
                entity="aircraft",
                event="depart",
                payload={"aircraft_id": int(self.aircraft_id), "pallet_id": int(pallet_id)},
            )

            yield self._env.timeout(self._flight_time)
            yield self._env.timeout(self._unload_time)

            delivery_time = float(self._env.now)
            pallet = self._registry.get(pallet_id)
            latency = delivery_time - pallet.generation_time
            self._emitter.emit(
                time=delivery_time,
                entity="destination",
                event="pallet_delivered",
                payload={"pallet_id": int(pallet_id), "aircraft_id": int(self.aircraft_id), "latency": float(latency)},
            )

            yield self._env.timeout(self._return_time)
            now = float(self._env.now)
            self._emitter.emit(
                time=now,
                entity="aircraft",
                event="return",
                payload={"aircraft_id": self.aircraft_id},
            )

            self._emitter.emit(
                time=now,
                entity="aircraft",
                event="maintenance_start",
                payload={"aircraft_id": self.aircraft_id},
            )
            yield self._env.timeout(self._maintenance_time)

            now = float(self._env.now)
            self._emitter.emit(
                time=now,
                entity="aircraft",
                event="maintenance_end",
                payload={"aircraft_id": self.aircraft_id},
            )

            self._coordinator.register_idle(self)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Airfreight logistics DES simulation (JSONL stdout).")
    p.add_argument("--duration", type=float, default=10000.0)
    p.add_argument("--num_aircraft", type=int, default=2)
    p.add_argument("--pallet_interval", type=float, default=25.0)
    p.add_argument("--pallet_expiration_time", type=float, default=150.0)
    p.add_argument("--flight_time", type=float, default=30.0)
    p.add_argument("--unload_time", type=float, default=2.0)
    p.add_argument("--return_time", type=float, default=30.0)
    p.add_argument("--maintenance_time", type=float, default=10.0)
    return p.parse_args(argv)


def main(argv=None):

    # Real-time safeguard: keep this DES run comfortably under 10 seconds.
    # This does NOT use real-time in simulation; it only caps event count.
    max_events = 200_000

    args = parse_args(argv)

    if args.num_aircraft < 1:
        LOGGER.error("--num_aircraft must be >= 1")
        return 2
    if args.duration < 0:
        LOGGER.error("--duration must be >= 0")
        return 2
    if args.pallet_interval <= 0:
        LOGGER.error("--pallet_interval must be > 0")
        return 2

    env = simpy.Environment()
    emitter = JsonlEmitter()
    registry = PalletRegistry()
    queue = LoadingQueue(emitter=emitter)
    coordinator = Coordinator(env=env, emitter=emitter, queue=queue, registry=registry)

    facility = Facility(
        env=env,
        emitter=emitter,
        registry=registry,
        queue=queue,
        coordinator=coordinator,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
    )
    facility.start()

    aircraft = [
        Aircraft(
            env=env,
            emitter=emitter,
            registry=registry,
            coordinator=coordinator,
            aircraft_id=i,
            flight_time=args.flight_time,
            unload_time=args.unload_time,
            return_time=args.return_time,
            maintenance_time=args.maintenance_time,
        )
        for i in range(1, args.num_aircraft + 1)
    ]
    for a in aircraft:
        a.start()

    LOGGER.info(
        "Starting simulation: duration=%s, num_aircraft=%s, pallet_interval=%s",
        args.duration,
        args.num_aircraft,
        args.pallet_interval,
    )

    until = float(args.duration)
    events = 0
    while True:
        if events >= max_events:
            LOGGER.warning("Max events (%s) reached; stopping early at t=%s", max_events, float(env.now))
            break

        next_t = env.peek()
        if next_t == float("inf"):
            if float(env.now) < until:
                env.run(until=until)
            break

        if next_t > until:
            env.run(until=until)
            break

        env.step()
        events += 1

    LOGGER.info("Simulation finished at t=%s (events=%s)", float(env.now), events)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
