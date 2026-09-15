#!/usr/bin/env python3
import argparse
import sys
import json
import logging
from collections import OrderedDict
import random  # allowed, may be unused

try:
    import xdevs  # type: ignore  # optional; not required for this implementation
except Exception:
    xdevs = None  # noqa: F841

import simpy


def emit(time_now: float, entity: str, event: str, payload: dict) -> None:
    # stdout must contain ONLY JSONL event objects
    sys.stdout.write(json.dumps({
        "time": float(time_now),
        "entity": entity,
        "event": event,
        "payload": payload
    }) + "\n")


class Notifier:
    """A resettable SimPy event used to wake waiters when something changes."""
    def __init__(self, env: simpy.Environment):
        self.env = env
        self._event = env.event()

    @property
    def event(self) -> simpy.Event:
        return self._event

    def notify(self) -> None:
        if not self._event.triggered:
            self._event.succeed()
        self._event = self.env.event()


class Pallet:
    __slots__ = ("pallet_id", "gen_time", "expiration_time", "assigned")

    def __init__(self, pallet_id: int, gen_time: float, expiration_time: float):
        self.pallet_id = pallet_id
        self.gen_time = gen_time
        self.expiration_time = expiration_time
        self.assigned = False


class LoadingQueue:
    def __init__(self, env: simpy.Environment, logger: logging.Logger):
        self.env = env
        self.logger = logger
        self._items: "OrderedDict[int, Pallet]" = OrderedDict()
        self.changed = Notifier(env)
        self.total_expired = 0

    def __len__(self) -> int:
        return len(self._items)

    def enqueue(self, pallet: Pallet) -> None:
        self._items[pallet.pallet_id] = pallet
        emit(self.env.now, "queue", "pallet_queued", {
            "pallet_id": pallet.pallet_id,
            "queue_size": len(self._items),
        })
        self.changed.notify()

    def contains(self, pallet_id: int) -> bool:
        return pallet_id in self._items

    def expire(self, pallet_id: int) -> bool:
        """Expire pallet if still present in queue. Returns True if expired."""
        pallet = self._items.get(pallet_id)
        if pallet is None:
            return False
        if pallet.assigned:
            # Should not happen if we removed it correctly, but safe.
            del self._items[pallet_id]
            self.changed.notify()
            return False

        del self._items[pallet_id]
        self.total_expired += 1
        emit(self.env.now, "queue", "pallet_expired", {
            "pallet_id": pallet_id,
            "total_expired": self.total_expired,
        })
        self.changed.notify()
        return True

    def pop_fifo(self) -> Pallet:
        pallet_id, pallet = self._items.popitem(last=False)
        return pallet


class Destination:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def delivered(self, pallet: Pallet, aircraft_id: int) -> None:
        latency = float(self.env.now - pallet.gen_time)
        emit(self.env.now, "destination", "pallet_delivered", {
            "pallet_id": pallet.pallet_id,
            "aircraft_id": aircraft_id,
            "latency": latency,
        })


class Aircraft:
    def __init__(
        self,
        env: simpy.Environment,
        aircraft_id: int,
        coordinator: "FleetCoordinator",
        destination: Destination,
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
        logger: logging.Logger
    ):
        self.env = env
        self.aircraft_id = aircraft_id
        self.coordinator = coordinator
        self.destination = destination
        self.flight_time = float(flight_time)
        self.unload_time = float(unload_time)
        self.return_time = float(return_time)
        self.maintenance_time = float(maintenance_time)
        self.logger = logger

        self.inbox = simpy.Store(env, capacity=1)  # receives Pallet assignments

    def assign(self, pallet: Pallet) -> None:
        # Assignment put is instantaneous at the coordinator's current time.
        self.inbox.put(pallet)

    def run(self):
        while True:
            # Become idle and wait for assignment
            self.coordinator.aircraft_idle(self.aircraft_id)
            pallet: Pallet = yield self.inbox.get()

            # Load is instantaneous; depart at assignment time
            emit(self.env.now, "aircraft", "depart", {
                "aircraft_id": self.aircraft_id,
                "pallet_id": pallet.pallet_id,
            })

            # Fly to destination
            if self.flight_time > 0:
                yield self.env.timeout(self.flight_time)

            # Unload (delivery on completion)
            if self.unload_time > 0:
                yield self.env.timeout(self.unload_time)
            self.destination.delivered(pallet, self.aircraft_id)

            # Return to facility
            if self.return_time > 0:
                yield self.env.timeout(self.return_time)
            emit(self.env.now, "aircraft", "return", {
                "aircraft_id": self.aircraft_id
            })

            # Maintenance
            emit(self.env.now, "aircraft", "maintenance_start", {
                "aircraft_id": self.aircraft_id
            })
            if self.maintenance_time > 0:
                yield self.env.timeout(self.maintenance_time)
            emit(self.env.now, "aircraft", "maintenance_end", {
                "aircraft_id": self.aircraft_id
            })


class FleetCoordinator:
    def __init__(
        self,
        env: simpy.Environment,
        queue: LoadingQueue,
        logger: logging.Logger
    ):
        self.env = env
        self.queue = queue
        self.logger = logger
        self._idle_aircraft = []  # list[int]
        self.idle_changed = Notifier(env)
        self.aircraft_by_id: dict[int, Aircraft] = {}

    def register_aircraft(self, aircraft: Aircraft) -> None:
        self.aircraft_by_id[aircraft.aircraft_id] = aircraft

    def aircraft_idle(self, aircraft_id: int) -> None:
        # Avoid duplicates (should not occur, but safe)
        if aircraft_id not in self._idle_aircraft:
            self._idle_aircraft.append(aircraft_id)
            self.idle_changed.notify()

    def run(self, duration: float):
        # Continuously create assignments whenever both supply and idle aircraft exist.
        while self.env.now < duration:
            # Drain as many assignments as possible at current sim time
            while len(self.queue) > 0 and self._idle_aircraft:
                aircraft_id = self._idle_aircraft.pop(0)
                pallet = self.queue.pop_fifo()
                pallet.assigned = True

                emit(self.env.now, "coordinator", "assignment_created", {
                    "aircraft_id": aircraft_id,
                    "pallet_id": pallet.pallet_id,
                })

                self.aircraft_by_id[aircraft_id].assign(pallet)

            # Wait for either queue change or aircraft availability (or sim end)
            remaining = duration - self.env.now
            if remaining <= 0:
                break
            wake = simpy.events.AnyOf(self.env, [self.queue.changed.event, self.idle_changed.event])
            yield wake


class Facility:
    def __init__(
        self,
        env: simpy.Environment,
        queue: LoadingQueue,
        pallet_interval: float,
        pallet_expiration_time: float,
        logger: logging.Logger
    ):
        self.env = env
        self.queue = queue
        self.pallet_interval = float(pallet_interval)
        self.pallet_expiration_time = float(pallet_expiration_time)
        self.logger = logger
        self._next_id = 1

    def _expire_process(self, pallet: Pallet):
        wait = max(0.0, float(pallet.expiration_time - self.env.now))
        if wait > 0:
            yield self.env.timeout(wait)
        else:
            # Still yield to allow same-time ordering behind creation/enqueue
            yield self.env.timeout(0)

        # Expire exactly at deadline if still in queue and not assigned
        if self.queue.contains(pallet.pallet_id) and (not pallet.assigned):
            self.queue.expire(pallet.pallet_id)

    def run(self, duration: float):
        while self.env.now < duration:
            pallet_id = self._next_id
            self._next_id += 1

            gen_time = float(self.env.now)
            expiration_time = gen_time + self.pallet_expiration_time
            pallet = Pallet(pallet_id=pallet_id, gen_time=gen_time, expiration_time=expiration_time)

            emit(self.env.now, "facility", "pallet_generated", {
                "pallet_id": pallet.pallet_id,
                "expiration_time": float(pallet.expiration_time),
            })

            self.queue.enqueue(pallet)
            self.env.process(self._expire_process(pallet))

            if self.pallet_interval <= 0:
                # Prevent infinite loop; generate only once if interval is 0 or negative
                break
            yield self.env.timeout(self.pallet_interval)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Airfreight logistics discrete-event simulation (JSONL output).")
    p.add_argument("--duration", type=float, default=10000.0)
    p.add_argument("--num_aircraft", type=int, default=2)
    p.add_argument("--pallet_interval", type=float, default=25.0)
    p.add_argument("--pallet_expiration_time", type=float, default=150.0)
    p.add_argument("--flight_time", type=float, default=30.0)
    p.add_argument("--unload_time", type=float, default=2.0)
    p.add_argument("--return_time", type=float, default=30.0)
    p.add_argument("--maintenance_time", type=float, default=10.0)
    return p


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(message)s"
    )
    logger = logging.getLogger("airfreight_sim")

    args = build_arg_parser().parse_args(argv)

    if args.num_aircraft < 1:
        logger.error("--num_aircraft must be >= 1")
        return 2
    if args.duration < 0:
        logger.error("--duration must be >= 0")
        return 2

    # Create simulation environment
    env = simpy.Environment()

    # Entities
    queue = LoadingQueue(env, logger=logger)
    destination = Destination(env)
    coordinator = FleetCoordinator(env, queue=queue, logger=logger)

    # Aircraft fleet
    aircraft_list = []
    for i in range(1, args.num_aircraft + 1):
        a = Aircraft(
            env=env,
            aircraft_id=i,
            coordinator=coordinator,
            destination=destination,
            flight_time=args.flight_time,
            unload_time=args.unload_time,
            return_time=args.return_time,
            maintenance_time=args.maintenance_time,
            logger=logger,
        )
        coordinator.register_aircraft(a)
        aircraft_list.append(a)
        env.process(a.run())

    # Facility
    facility = Facility(
        env=env,
        queue=queue,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
        logger=logger
    )
    env.process(facility.run(args.duration))

    # Coordinator
    env.process(coordinator.run(args.duration))

    logger.info("Starting simulation: duration=%s, aircraft=%s", args.duration, args.num_aircraft)
    env.run(until=float(args.duration))
    logger.info("Simulation finished at t=%s", env.now)

    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        # Allow piping to tools like `head` without stack traces
        raise SystemExit(0)