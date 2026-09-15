#!/usr/bin/env python3
"""Airfreight logistics DES simulation.

Entry point: python run.py

Stdout: JSONL event stream ONLY.
Stderr: logs/debug.
"""

import argparse
import json
import logging
import sys
from collections import deque, namedtuple

import simpy


# -------------------------
# Event emission (stdout)
# -------------------------

def emit(time: float, entity: str, event: str, payload: dict) -> None:
    """Emit a single JSONL event to stdout.

    Important: stdout must contain ONLY JSONL lines.

    If stdout is closed (e.g., piped to `head`), we stop the simulation cleanly.
    """
    obj = {
        "time": float(time),
        "entity": str(entity),
        "event": str(event),
        "payload": payload if isinstance(payload, dict) else dict(payload),
    }
    try:
        sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    except BrokenPipeError:
        # Downstream consumer closed the pipe; end quickly.
        # Provide a value to satisfy SimPy's Environment.run() return handling.
        raise simpy.core.StopSimulation(0)  # type: ignore[attr-defined]


# -------------------------
# Domain model
# -------------------------


Pallet = namedtuple("Pallet", ["pallet_id", "generation_time", "expiration_time"])


class Notifier:
    """Broadcast-style notification primitive for SimPy.

    Multiple consumers can wait() concurrently; notify() wakes all of them.

    This is used to wake the coordinator and queue expiration monitor whenever the
    system state changes.
    """

    def __init__(self, env: simpy.Environment):
        self._env = env
        self._event = env.event()

    def notify(self) -> None:
        # Succeed the current event (waking all waiters), then create a fresh one.
        if not self._event.triggered:
            self._event.succeed()
        self._event = self._env.event()

    def wait(self):
        return self._event


class LoadingQueue:
    def __init__(self, env: simpy.Environment, notifier: Notifier, logger: logging.Logger):
        self.env = env
        self.notifier = notifier
        self.logger = logger

        self._dq = deque()  # FIFO of Pallet
        self._expired_total = 0

        # One background process handles expirations (no per-pallet watcher).
        self.env.process(self._expire_monitor())

    def __len__(self) -> int:
        return len(self._dq)

    def add(self, pallet: Pallet) -> None:
        self._dq.append(pallet)
        emit(
            self.env.now,
            "queue",
            "pallet_queued",
            {"pallet_id": pallet.pallet_id, "queue_size": len(self._dq)},
        )
        self.notifier.notify()

    def purge_expired(self) -> None:
        """Expire all pallets whose deadline has been reached (time <= now).

        Because expiration_time = generation_time + constant, FIFO order is also
        expiration order. So only the head can become expired first.
        """
        while self._dq and self._dq[0].expiration_time <= self.env.now:
            pallet = self._dq.popleft()
            self._expired_total += 1
            emit(
                self.env.now,
                "queue",
                "pallet_expired",
                {"pallet_id": pallet.pallet_id, "total_expired": self._expired_total},
            )

    def pop_fifo(self):
        # Ensure expirations at exactly now happen before any assignment.
        self.purge_expired()
        if not self._dq:
            return None
        pallet = self._dq.popleft()
        self.notifier.notify()
        return pallet

    def _expire_monitor(self):
        """Wake up exactly at the next deadline and expire immediately."""
        while True:
            if not self._dq:
                yield self.notifier.wait()
                continue

            # Sleep until the next pallet's deadline.
            next_deadline = self._dq[0].expiration_time
            delay = next_deadline - self.env.now
            if delay > 0:
                yield self.env.timeout(delay)

            # Expire everything that should be expired at this time.
            self.purge_expired()
            self.notifier.notify()


class Aircraft:
    def __init__(
        self,
        env: simpy.Environment,
        notifier: Notifier,
        logger: logging.Logger,
        aircraft_id: int,
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
        pallet_gen_times: dict,
    ):
        self.env = env
        self.notifier = notifier
        self.logger = logger

        self.aircraft_id = aircraft_id
        self.flight_time = float(flight_time)
        self.unload_time = float(unload_time)
        self.return_time = float(return_time)
        self.maintenance_time = float(maintenance_time)

        self.state = "idle"  # idle, in_flight, unloading, returning, maintenance

        self._assigned = simpy.Store(env, capacity=1)  # holds Pallet
        self._pallet_gen_times = pallet_gen_times

        # Start behavior.
        self.env.process(self._run())

    def try_assign(self, pallet: Pallet) -> bool:
        """Assign a pallet if (and only if) aircraft is idle."""
        if not self.is_idle():
            return False
        # Mark non-idle immediately to prevent double-assignment in the same tick.
        self.state = "in_flight"
        self._assigned.put(pallet)
        return True

    def is_idle(self) -> bool:
        return self.state == "idle" and len(self._assigned.items) == 0

    def _run(self):
        while True:
            pallet = yield self._assigned.get()  # Pallet

            # Depart time is exactly assignment time (load is instantaneous).
            emit(
                self.env.now,
                "aircraft",
                "depart",
                {"aircraft_id": self.aircraft_id, "pallet_id": pallet.pallet_id},
            )

            # Fly to destination.
            if self.flight_time > 0:
                yield self.env.timeout(self.flight_time)

            # Unload.
            self.state = "unloading"
            if self.unload_time > 0:
                yield self.env.timeout(self.unload_time)

            # Delivery recorded at unload completion.
            gen_t = self._pallet_gen_times.get(pallet.pallet_id, pallet.generation_time)
            emit(
                self.env.now,
                "destination",
                "pallet_delivered",
                {
                    "pallet_id": pallet.pallet_id,
                    "aircraft_id": self.aircraft_id,
                    "latency": float(self.env.now - gen_t),
                },
            )

            # Return.
            self.state = "returning"
            if self.return_time > 0:
                yield self.env.timeout(self.return_time)

            emit(self.env.now, "aircraft", "return", {"aircraft_id": self.aircraft_id})

            # Maintenance.
            self.state = "maintenance"
            emit(
                self.env.now,
                "aircraft",
                "maintenance_start",
                {"aircraft_id": self.aircraft_id},
            )
            if self.maintenance_time > 0:
                yield self.env.timeout(self.maintenance_time)
            emit(
                self.env.now,
                "aircraft",
                "maintenance_end",
                {"aircraft_id": self.aircraft_id},
            )

            self.state = "idle"
            self.notifier.notify()


class FleetCoordinator:
    def __init__(
        self,
        env: simpy.Environment,
        notifier: Notifier,
        logger: logging.Logger,
        queue: LoadingQueue,
        aircraft: list,
    ):
        self.env = env
        self.notifier = notifier
        self.logger = logger
        self.queue = queue
        self.aircraft = aircraft

        self.env.process(self._run())

    def _idle_aircraft(self):
        # Iterate in stable order for fairness across aircraft IDs.
        for a in self.aircraft:
            if a.is_idle():
                return a
        return None

    def _try_assign_once(self) -> bool:
        # Expire any pallets due at this exact time before considering assignments.
        self.queue.purge_expired()
        if len(self.queue) == 0:
            return False
        aircraft = self._idle_aircraft()
        if aircraft is None:
            return False
        pallet = self.queue.pop_fifo()
        if pallet is None:
            return False

        # First reserve the aircraft, then emit assignment event.
        # This prevents multiple pallets being assigned to the same aircraft in
        # the same simulation instant.
        if not aircraft.try_assign(pallet):
            # Lost the race; put pallet back at front to preserve FIFO.
            self.queue._dq.appendleft(pallet)  # internal but safe here
            return False

        emit(
            self.env.now,
            "coordinator",
            "assignment_created",
            {"aircraft_id": aircraft.aircraft_id, "pallet_id": pallet.pallet_id},
        )
        return True

    def _run(self):
        while True:
            made_any = False
            while self._try_assign_once():
                made_any = True
            if not made_any:
                yield self.notifier.wait()


class Facility:
    def __init__(
        self,
        env: simpy.Environment,
        notifier: Notifier,
        logger: logging.Logger,
        queue: LoadingQueue,
        duration: float,
        pallet_interval: float,
        pallet_expiration_time: float,
        pallet_gen_times: dict,
    ):
        self.env = env
        self.notifier = notifier
        self.logger = logger
        self.queue = queue

        self.duration = float(duration)
        self.pallet_interval = float(pallet_interval)
        self.pallet_expiration_time = float(pallet_expiration_time)
        self.pallet_gen_times = pallet_gen_times

        self._next_pallet_id = 1
        self.env.process(self._run())

    def _run(self):
        # Generate at t=0, t+interval, ... while strictly before duration.
        # (Events at exactly t==duration are excluded; env.run will stop at duration.)
        while True:
            if self.env.now >= self.duration:
                break

            pid = self._next_pallet_id
            self._next_pallet_id += 1

            gen_t = float(self.env.now)
            exp_t = gen_t + self.pallet_expiration_time
            pallet = Pallet(pallet_id=pid, generation_time=gen_t, expiration_time=exp_t)
            self.pallet_gen_times[pid] = gen_t

            emit(
                self.env.now,
                "facility",
                "pallet_generated",
                {"pallet_id": pid, "expiration_time": float(exp_t)},
            )

            # Immediately queued.
            self.queue.add(pallet)
            self.notifier.notify()

            if self.pallet_interval <= 0:
                # Avoid infinite loop; generate once.
                self.logger.warning("pallet_interval <= 0; generating only one pallet")
                break

            yield self.env.timeout(self.pallet_interval)


# -------------------------
# CLI / main
# -------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Airfreight logistics DES simulation (JSONL stdout)")
    p.add_argument("--duration", type=float, default=10000.0, help="Total simulation time")
    p.add_argument("--num_aircraft", type=int, default=2, help="Number of aircraft (>=1)")
    p.add_argument("--pallet_interval", type=float, default=25.0, help="Interval between pallet generations")
    p.add_argument(
        "--pallet_expiration_time",
        type=float,
        default=150.0,
        help="Time until pallet expires while waiting in queue",
    )
    p.add_argument("--flight_time", type=float, default=30.0, help="Flight duration")
    p.add_argument("--unload_time", type=float, default=2.0, help="Unload duration")
    p.add_argument("--return_time", type=float, default=30.0, help="Return flight duration")
    p.add_argument("--maintenance_time", type=float, default=10.0, help="Maintenance duration")
    return p


def _validate_args(args: argparse.Namespace, logger: logging.Logger) -> None:
    if args.num_aircraft < 1:
        raise SystemExit("--num_aircraft must be >= 1")
    for name in [
        "duration",
        "pallet_interval",
        "pallet_expiration_time",
        "flight_time",
        "unload_time",
        "return_time",
        "maintenance_time",
    ]:
        val = getattr(args, name)
        if val < 0:
            raise SystemExit(f"--{name} must be >= 0")

    # Hard safety limit to guarantee the program finishes quickly in wall time.
    # (We do not use real time in the simulation logic; instead we prevent
    # configurations that would produce enormous amounts of events/output.)
    if args.duration <= 0:
        expected_pallets = 0
    elif args.pallet_interval <= 0:
        expected_pallets = 1
    else:
        # Facility generates at t=0, interval, 2*interval, ... strictly < duration.
        expected_pallets = int((args.duration - 1e-12) // args.pallet_interval) + 1

    # Upper bound on JSONL lines per pallet: generated + queued +
    # (assignment + depart + delivered + return + maint_start + maint_end).
    max_events_bound = expected_pallets * 8

    MAX_PALLETS = 20_000
    MAX_EVENTS_BOUND = 200_000
    if expected_pallets > MAX_PALLETS or max_events_bound > MAX_EVENTS_BOUND:
        raise SystemExit(
            "Refusing to run: configuration would generate too many events "
            f"(expected_pallets={expected_pallets}, max_events_bound={max_events_bound}). "
            "Reduce --duration and/or increase --pallet_interval."
        )

    if expected_pallets > 5_000:
        logger.warning(
            "Large run: expected_pallets=%s (max_events_bound=%s)",
            expected_pallets,
            max_events_bound,
        )


def main(argv: list[str]) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s:%(message)s")
    logger = logging.getLogger("airfreight")

    args = build_arg_parser().parse_args(argv)
    _validate_args(args, logger)

    env = simpy.Environment()
    notifier = Notifier(env)

    pallet_gen_times = {}

    queue = LoadingQueue(env=env, notifier=notifier, logger=logger)

    aircraft_list = [
        Aircraft(
            env=env,
            notifier=notifier,
            logger=logger,
            aircraft_id=i + 1,
            flight_time=args.flight_time,
            unload_time=args.unload_time,
            return_time=args.return_time,
            maintenance_time=args.maintenance_time,
            pallet_gen_times=pallet_gen_times,
        )
        for i in range(args.num_aircraft)
    ]

    FleetCoordinator(env=env, notifier=notifier, logger=logger, queue=queue, aircraft=aircraft_list)

    Facility(
        env=env,
        notifier=notifier,
        logger=logger,
        queue=queue,
        duration=args.duration,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
        pallet_gen_times=pallet_gen_times,
    )

    # Run simulation using simulation time only.
    # Use an Event as stop marker so events at exactly duration are processed.
    stop_event = env.timeout(args.duration)
    env.run(until=stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
