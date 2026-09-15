#!/usr/bin/env python3
import argparse
import sys
import json
import logging
from collections import deque
import random  # allowed; not required but kept per requirements

import simpy

# Optional: requirement mentions xdevs; keep import attempt without hard dependency.
try:
    import xdevs  # type: ignore  # noqa: F401
except Exception:
    xdevs = None  # noqa: F401


def jlog(time_now: float, entity: str, event: str, payload: dict) -> None:
    """JSONL logger to stdout only (no other stdout output allowed)."""
    sys.stdout.write(json.dumps({
        "time": float(time_now),
        "entity": entity,
        "event": event,
        "payload": payload
    }) + "\n")


class Pallet:
    __slots__ = ("pallet_id", "gen_time", "expiration_time")

    def __init__(self, pallet_id: int, gen_time: float, expiration_time: float):
        self.pallet_id = pallet_id
        self.gen_time = gen_time
        self.expiration_time = expiration_time


class LoadingQueue:
    """
    FIFO queue with active expiration:
    - Each pallet has an absolute expiration time.
    - If expiration time is reached while still queued, it is discarded immediately.
    """
    def __init__(self, env: simpy.Environment, coordinator: "FleetCoordinator"):
        self.env = env
        self.coordinator = coordinator

        self._fifo_ids = deque()         # FIFO of pallet_ids (may contain expired/removed ids; lazily skipped)
        self._in_queue = set()           # pallet_ids currently queued
        self._pallets = {}               # pallet_id -> Pallet

        self.total_expired = 0

    def __len__(self) -> int:
        return len(self._in_queue)

    def _cleanup_front(self) -> None:
        while self._fifo_ids and self._fifo_ids[0] not in self._in_queue:
            self._fifo_ids.popleft()

    def put(self, pallet: Pallet) -> None:
        pid = pallet.pallet_id
        self._fifo_ids.append(pid)
        self._in_queue.add(pid)
        self._pallets[pid] = pallet

        jlog(self.env.now, "queue", "pallet_queued", {
            "pallet_id": pid,
            "queue_size": len(self._in_queue)
        })

        # Start per-pallet expiration watcher
        self.env.process(self._expire_at(pallet))
        self.coordinator.wakeup()

    def has_pallet(self) -> bool:
        self._cleanup_front()
        return len(self._in_queue) > 0

    def get_next(self) -> Pallet:
        self._cleanup_front()
        if not self._fifo_ids:
            raise RuntimeError("Queue empty: no pallet available")
        pid = self._fifo_ids.popleft()
        while pid not in self._in_queue:
            # should be rare due to cleanup, but safe
            if not self._fifo_ids:
                raise RuntimeError("Queue empty after skipping removed ids")
            pid = self._fifo_ids.popleft()

        self._in_queue.remove(pid)
        pallet = self._pallets.pop(pid)
        return pallet

    def _expire_at(self, pallet: Pallet):
        # Wait until absolute expiration time
        delay = max(0.0, pallet.expiration_time - self.env.now)
        yield self.env.timeout(delay)

        pid = pallet.pallet_id
        if pid in self._in_queue:
            # Still in queue -> expire immediately
            self._in_queue.remove(pid)
            self._pallets.pop(pid, None)
            self.total_expired += 1
            jlog(self.env.now, "queue", "pallet_expired", {
                "pallet_id": pid,
                "total_expired": self.total_expired
            })
            self.coordinator.wakeup()


class Destination:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def delivered(self, pallet: Pallet, aircraft_id: int, delivery_time: float) -> None:
        latency = float(delivery_time - pallet.gen_time)
        jlog(delivery_time, "destination", "pallet_delivered", {
            "pallet_id": pallet.pallet_id,
            "aircraft_id": aircraft_id,
            "latency": latency
        })


class Aircraft:
    """
    Single-pallet capacity aircraft cycle:
      assign/load (0) -> fly -> unload -> return -> maintenance -> idle
    """
    def __init__(
        self,
        env: simpy.Environment,
        coordinator: "FleetCoordinator",
        destination: Destination,
        aircraft_id: int,
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
    ):
        self.env = env
        self.coordinator = coordinator
        self.destination = destination
        self.aircraft_id = aircraft_id

        self.flight_time = float(flight_time)
        self.unload_time = float(unload_time)
        self.return_time = float(return_time)
        self.maintenance_time = float(maintenance_time)

        self._busy = False

    @property
    def is_idle(self) -> bool:
        return not self._busy

    def assign(self, pallet: Pallet) -> None:
        if self._busy:
            raise RuntimeError(f"Aircraft-{self.aircraft_id} assigned while busy")
        self._busy = True
        self.env.process(self._cycle(pallet))

    def _cycle(self, pallet: Pallet):
        # Load is instantaneous; depart at assignment time
        jlog(self.env.now, "aircraft", "depart", {
            "aircraft_id": self.aircraft_id,
            "pallet_id": pallet.pallet_id
        })

        # Fly to destination
        yield self.env.timeout(self.flight_time)

        # Unload (delivery at unload completion)
        yield self.env.timeout(self.unload_time)
        self.destination.delivered(pallet, self.aircraft_id, self.env.now)

        # Return flight
        yield self.env.timeout(self.return_time)
        jlog(self.env.now, "aircraft", "return", {
            "aircraft_id": self.aircraft_id
        })

        # Maintenance
        jlog(self.env.now, "aircraft", "maintenance_start", {
            "aircraft_id": self.aircraft_id
        })
        yield self.env.timeout(self.maintenance_time)
        jlog(self.env.now, "aircraft", "maintenance_end", {
            "aircraft_id": self.aircraft_id
        })

        # Back to idle
        self._busy = False
        self.coordinator.notify_aircraft_idle(self.aircraft_id)


class Facility:
    def __init__(
        self,
        env: simpy.Environment,
        queue: LoadingQueue,
        pallet_interval: float,
        pallet_expiration_time: float,
        duration: float,
        max_pallets: int,
    ):
        self.env = env
        self.queue = queue
        self.pallet_interval = float(pallet_interval)
        self.pallet_expiration_time = float(pallet_expiration_time)
        self.duration = float(duration)
        self.max_pallets = int(max_pallets)

        self._next_id = 1

    def run(self):
        # Generate at t=0, then every pallet_interval
        while self.env.now <= self.duration:
            if self._next_id > self.max_pallets:
                logging.warning(
                    "Max pallet limit reached (%d). Stopping further generation to guarantee runtime.",
                    self.max_pallets
                )
                return

            pid = self._next_id
            self._next_id += 1

            gen_time = float(self.env.now)
            expiration_time = gen_time + self.pallet_expiration_time
            pallet = Pallet(pid, gen_time, expiration_time)

            jlog(self.env.now, "facility", "pallet_generated", {
                "pallet_id": pid,
                "expiration_time": float(expiration_time)
            })

            self.queue.put(pallet)

            # Schedule next generation
            if self.pallet_interval <= 0.0:
                logging.warning("pallet_interval <= 0; generating only one pallet to avoid infinite loop.")
                return
            yield self.env.timeout(self.pallet_interval)


class FleetCoordinator:
    def __init__(self, env: simpy.Environment, queue: LoadingQueue):
        self.env = env
        self.queue = queue

        self.aircraft = {}          # aircraft_id -> Aircraft
        self.idle_aircraft = set()  # set of aircraft_id

        self._wakeup_event = env.event()

    def add_aircraft(self, ac: Aircraft) -> None:
        self.aircraft[ac.aircraft_id] = ac
        if ac.is_idle:
            self.idle_aircraft.add(ac.aircraft_id)
        self.wakeup()

    def notify_aircraft_idle(self, aircraft_id: int) -> None:
        self.idle_aircraft.add(aircraft_id)
        self.wakeup()

    def wakeup(self) -> None:
        if not self._wakeup_event.triggered:
            self._wakeup_event.succeed()
        self._wakeup_event = self.env.event()

    def run(self, duration: float):
        duration = float(duration)
        while self.env.now < duration:
            # Try to assign as much as possible at current time
            assigned_any = False
            while self.queue.has_pallet() and self.idle_aircraft:
                # Deterministic selection: smallest aircraft_id
                aircraft_id = min(self.idle_aircraft)
                self.idle_aircraft.remove(aircraft_id)

                pallet = self.queue.get_next()

                jlog(self.env.now, "coordinator", "assignment_created", {
                    "aircraft_id": aircraft_id,
                    "pallet_id": pallet.pallet_id
                })

                self.aircraft[aircraft_id].assign(pallet)
                assigned_any = True

            # Wait until something changes or time ends
            remaining = duration - float(self.env.now)
            if remaining <= 0:
                break
            # If we just assigned, loop immediately to potentially assign again (rarely needed),
            # otherwise wait for changes.
            if not assigned_any:
                yield (self._wakeup_event | self.env.timeout(remaining))
            else:
                yield self.env.timeout(0)


def parse_args(argv):
    p = argparse.ArgumentParser(description="Airfreight logistics discrete-event simulation (JSONL output).")

    p.add_argument("--duration", type=float, default=10000.0)
    p.add_argument("--num_aircraft", type=int, default=2)
    p.add_argument("--pallet_interval", type=float, default=25.0)
    p.add_argument("--pallet_expiration_time", type=float, default=150.0)
    p.add_argument("--flight_time", type=float, default=30.0)
    p.add_argument("--unload_time", type=float, default=2.0)
    p.add_argument("--return_time", type=float, default=30.0)
    p.add_argument("--maintenance_time", type=float, default=10.0)

    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])

    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s:%(message)s")

    if args.num_aircraft < 1:
        logging.error("--num_aircraft must be >= 1")
        return 2
    if args.duration < 0:
        logging.error("--duration must be >= 0")
        return 2

    # Runtime safety: cap number of generated pallets to keep execution comfortably under 10s.
    # Default settings are far below this.
    MAX_PALLETS = 200_000

    # Estimate expected pallets; warn if huge (likely to exceed runtime).
    if args.pallet_interval > 0:
        est = int(args.duration / args.pallet_interval) + 1
        if est > MAX_PALLETS:
            logging.warning(
                "Estimated pallets (%d) exceed safety cap (%d). Generation will stop at cap.",
                est, MAX_PALLETS
            )
    else:
        logging.warning("pallet_interval <= 0 provided; generation will be limited to one pallet.")

    env = simpy.Environment()

    # Build components
    destination = Destination(env)
    # coordinator needs queue; queue needs coordinator -> create coordinator first with placeholder then link
    coordinator = FleetCoordinator(env, queue=None)  # type: ignore
    queue = LoadingQueue(env, coordinator)
    coordinator.queue = queue

    facility = Facility(
        env=env,
        queue=queue,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
        duration=args.duration,
        max_pallets=MAX_PALLETS,
    )

    # Create aircraft
    for i in range(1, args.num_aircraft + 1):
        ac = Aircraft(
            env=env,
            coordinator=coordinator,
            destination=destination,
            aircraft_id=i,
            flight_time=args.flight_time,
            unload_time=args.unload_time,
            return_time=args.return_time,
            maintenance_time=args.maintenance_time,
        )
        coordinator.add_aircraft(ac)

    # Start processes
    env.process(facility.run())
    env.process(coordinator.run(args.duration))

    # Run simulation to the requested simulation time.
    # No real-time usage; simpy will process as fast as possible.
    env.run(until=float(args.duration))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())