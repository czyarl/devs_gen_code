import argparse
import json
import logging
import sys
import time
from collections import deque, namedtuple

import random  # noqa: F401  (allowed stdlib; may be useful for extensions)

try:
    import xdevs  # type: ignore  # noqa: F401
except Exception:  # pragma: no cover
    xdevs = None  # type: ignore

import simpy


logger = logging.getLogger("airfreight_sim")


def emit(t: float, entity: str, event: str, payload: dict) -> None:
    sys.stdout.write(
        json.dumps({"time": float(t), "entity": entity, "event": event, "payload": payload}) + "\n"
    )
    sys.stdout.flush()


Pallet = namedtuple("Pallet", ["pallet_id", "generation_time", "expiration_time"])


class LoadingQueue:
    def __init__(self, env: simpy.Environment):
        self.env = env
        self._items: deque[Pallet] = deque()
        self.total_expired = 0
        self.changed = env.event()

    def _notify_changed(self) -> None:
        if not self.changed.triggered:
            self.changed.succeed()
        self.changed = self.env.event()

    def put(self, pallet: Pallet) -> None:
        self._items.append(pallet)
        emit(
            self.env.now,
            "queue",
            "pallet_queued",
            {"pallet_id": pallet.pallet_id, "queue_size": len(self._items)},
        )
        self._notify_changed()

    def peek(self) -> Pallet | None:
        return self._items[0] if self._items else None

    def expire_due(self) -> None:
        now = float(self.env.now)
        while self._items and self._items[0].expiration_time <= now:
            expired = self._items.popleft()
            self.total_expired += 1
            emit(
                self.env.now,
                "queue",
                "pallet_expired",
                {"pallet_id": expired.pallet_id, "total_expired": self.total_expired},
            )
            self._notify_changed()

    def pop_next_nonexpired(self) -> Pallet | None:
        self.expire_due()
        if not self._items:
            return None
        pallet = self._items.popleft()
        self._notify_changed()
        return pallet

    def __len__(self) -> int:
        return len(self._items)


class Aircraft:
    def __init__(
        self,
        env: simpy.Environment,
        aircraft_id: int,
        *,
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
        destination: "Destination",
        idle_store: simpy.Store,
    ):
        self.env = env
        self.aircraft_id = aircraft_id
        self.flight_time = float(flight_time)
        self.unload_time = float(unload_time)
        self.return_time = float(return_time)
        self.maintenance_time = float(maintenance_time)
        self.destination = destination
        self.idle_store = idle_store
        self._assignments: simpy.Store = simpy.Store(env, capacity=1)
        self._proc = env.process(self._run())

    def assign(self, pallet: Pallet) -> simpy.Event:
        return self._assignments.put(pallet)

    def _run(self):
        while True:
            pallet: Pallet = yield self._assignments.get()

            emit(
                self.env.now,
                "aircraft",
                "depart",
                {"aircraft_id": self.aircraft_id, "pallet_id": pallet.pallet_id},
            )

            yield self.env.timeout(self.flight_time)

            yield self.env.timeout(self.unload_time)
            self.destination.deliver(pallet, aircraft_id=self.aircraft_id)

            yield self.env.timeout(self.return_time)
            emit(self.env.now, "aircraft", "return", {"aircraft_id": self.aircraft_id})

            emit(
                self.env.now,
                "aircraft",
                "maintenance_start",
                {"aircraft_id": self.aircraft_id},
            )
            yield self.env.timeout(self.maintenance_time)

            emit(
                self.env.now,
                "aircraft",
                "maintenance_end",
                {"aircraft_id": self.aircraft_id},
            )

            self.idle_store.put(self)


class Destination:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def deliver(self, pallet: Pallet, *, aircraft_id: int) -> None:
        emit(
            self.env.now,
            "destination",
            "pallet_delivered",
            {
                "pallet_id": pallet.pallet_id,
                "aircraft_id": aircraft_id,
                "latency": float(self.env.now) - pallet.generation_time,
            },
        )


def facility_process(
    env: simpy.Environment,
    queue: LoadingQueue,
    *,
    pallet_interval: float,
    pallet_expiration_time: float,
):
    pallet_id = 1
    while True:
        gen_time = float(env.now)
        expiration_time = gen_time + float(pallet_expiration_time)
        pallet = Pallet(pallet_id=pallet_id, generation_time=gen_time, expiration_time=expiration_time)

        emit(
            env.now,
            "facility",
            "pallet_generated",
            {"pallet_id": pallet.pallet_id, "expiration_time": pallet.expiration_time},
        )
        queue.put(pallet)

        pallet_id += 1
        yield env.timeout(float(pallet_interval))


def queue_expiration_monitor(env: simpy.Environment, queue: LoadingQueue):
    while True:
        queue.expire_due()
        head = queue.peek()
        if head is None:
            yield queue.changed
            continue

        wait = float(head.expiration_time) - float(env.now)
        if wait <= 0:
            continue

        yield simpy.AnyOf(env, [env.timeout(wait), queue.changed])


def coordinator_process(env: simpy.Environment, queue: LoadingQueue, idle_aircraft: simpy.Store):
    while True:
        queue.expire_due()

        if len(queue) == 0:
            yield queue.changed
            continue

        aircraft: Aircraft = yield idle_aircraft.get()
        queue.expire_due()

        pallet = queue.pop_next_nonexpired()
        if pallet is None:
            idle_aircraft.put(aircraft)
            continue

        emit(
            env.now,
            "coordinator",
            "assignment_created",
            {"aircraft_id": aircraft.aircraft_id, "pallet_id": pallet.pallet_id},
        )
        aircraft.assign(pallet)


def _positive_float(value: str) -> float:
    v = float(value)
    if v <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return v


def stopper_process(env: simpy.Environment, duration: float):
    # Ensures the environment reaches `duration` exactly even if no other events are scheduled then.
    yield env.timeout(float(duration))



def _nonnegative_float(value: str) -> float:
    v = float(value)
    if v < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return v


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Airfreight logistics DES simulation (JSONL output).")

    p.add_argument("--duration", type=_nonnegative_float, default=10000.0)
    p.add_argument("--num_aircraft", type=int, default=2)

    p.add_argument("--pallet_interval", type=_positive_float, default=25.0)
    p.add_argument("--pallet_expiration_time", type=_nonnegative_float, default=150.0)

    p.add_argument("--flight_time", type=_nonnegative_float, default=30.0)
    p.add_argument("--unload_time", type=_nonnegative_float, default=2.0)
    p.add_argument("--return_time", type=_nonnegative_float, default=30.0)
    p.add_argument("--maintenance_time", type=_nonnegative_float, default=10.0)

    args = p.parse_args(argv)

    if args.num_aircraft < 1:
        p.error("--num_aircraft must be >= 1")

    return args


def run_with_watchdog(env: simpy.Environment, *, until: float, wall_clock_limit_s: float = 9.0) -> None:
    start = time.perf_counter()

    # Step the environment manually so we can enforce a hard wall-clock bound.
    while True:
        next_t = env.peek()
        if next_t == float("inf") or float(next_t) > float(until):
            break

        env.step()

        if (time.perf_counter() - start) >= wall_clock_limit_s:
            logger.warning(
                "Wall-clock limit reached; stopping early at simulation time %.6f (target %.6f)",
                float(env.now),
                float(until),
            )
            break


def main(argv: list[str]) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(levelname)s:%(message)s")

    args = parse_args(argv)

    # Basic sanity cap: helps keep runs fast even with extreme parameters.
    if args.duration > 0:
        est_pallets = int(args.duration / args.pallet_interval) + 1
        if est_pallets > 2_000_000:
            logger.warning(
                "Extremely high pallet count estimate (%d). Run may stop early.",
                est_pallets,
            )

    env = simpy.Environment()
    destination = Destination(env)
    queue = LoadingQueue(env)

    idle_aircraft: simpy.Store = simpy.Store(env)
    aircraft_list: list[Aircraft] = []
    for i in range(1, args.num_aircraft + 1):
        a = Aircraft(
            env,
            i,
            flight_time=args.flight_time,
            unload_time=args.unload_time,
            return_time=args.return_time,
            maintenance_time=args.maintenance_time,
            destination=destination,
            idle_store=idle_aircraft,
        )
        aircraft_list.append(a)
        idle_aircraft.put(a)

    env.process(
        facility_process(
            env,
            queue,
            pallet_interval=args.pallet_interval,
            pallet_expiration_time=args.pallet_expiration_time,
        )
    )
    env.process(queue_expiration_monitor(env, queue))
    env.process(coordinator_process(env, queue, idle_aircraft))
    env.process(stopper_process(env, float(args.duration)))

    run_with_watchdog(env, until=float(args.duration))

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
