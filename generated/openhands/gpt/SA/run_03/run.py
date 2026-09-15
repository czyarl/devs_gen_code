#!/usr/bin/env python3
"""Airfreight logistics DES simulation.

STDOUT: JSONL event stream (and only that).
STDERR: debug/log messages.

Implements a simple discrete-event simulator (priority queue scheduler) to model:
- facility pallet generation
- loading queue with deadline expiration
- coordinator assigning FIFO pallets to idle aircraft
- aircraft transport cycle with delivery at end of unload

"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
import heapq


# ----------------------------- Logging (stderr) -----------------------------

def _configure_logging() -> None:
    # All logs must go to stderr; keep it quiet by default.
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
        stream=sys.stderr,
    )


logger = logging.getLogger("airfreight_sim")


# --------------------------- Discrete Event Engine --------------------------

EventFn = Callable[[], None]


@dataclass(order=True)
class _ScheduledEvent:
    time: float
    priority: int
    seq: int
    fn: EventFn


class Simulator:
    """Minimal DES scheduler using a heap-based future event list."""

    def __init__(self, duration: float):
        self.duration = float(duration)
        self.now: float = 0.0
        self._seq: int = 0
        self._fel: List[_ScheduledEvent] = []

    def schedule(self, time: float, priority: int, fn: EventFn) -> None:
        """Schedule an event at absolute simulation time.

        Events beyond duration are allowed but will never execute.
        """
        self._seq += 1
        heapq.heappush(self._fel, _ScheduledEvent(float(time), int(priority), self._seq, fn))

    def run(self) -> None:
        while self._fel:
            ev = heapq.heappop(self._fel)
            if ev.time > self.duration:
                break
            self.now = ev.time
            ev.fn()


# --------------------------------- Model -----------------------------------


def emit(time: float, entity: str, event: str, payload: Dict[str, Any]) -> None:
    """Emit a JSONL event to stdout, and nothing else."""
    sys.stdout.write(
        json.dumps(
            {
                "time": float(time),
                "entity": entity,
                "event": event,
                "payload": payload,
            },
            separators=(",", ":"),
        )
        + "\n"
    )


class LoadingQueue:
    """FIFO queue with per-pallet expiration, supporting O(1) FIFO and deletes."""

    def __init__(self):
        # pallet_id -> expiration_time
        self._q: "OrderedDict[int, float]" = OrderedDict()

    def __len__(self) -> int:
        return len(self._q)

    def enqueue(self, pallet_id: int, expiration_time: float) -> None:
        self._q[pallet_id] = float(expiration_time)

    def contains(self, pallet_id: int) -> bool:
        return pallet_id in self._q

    def dequeue_fifo(self) -> Tuple[int, float]:
        return self._q.popitem(last=False)

    def remove(self, pallet_id: int) -> None:
        del self._q[pallet_id]


@dataclass
class PalletInfo:
    pallet_id: int
    gen_time: float
    expiration_time: float
    assigned: bool = False  # once assigned to aircraft, deadline no longer matters


class Aircraft:
    def __init__(
        self,
        sim: Simulator,
        coordinator: "Coordinator",
        aircraft_id: int,
        flight_time: float,
        unload_time: float,
        return_time: float,
        maintenance_time: float,
        pallet_info: Dict[int, PalletInfo],
    ):
        self.sim = sim
        self.coordinator = coordinator
        self.aircraft_id = int(aircraft_id)

        self.flight_time = float(flight_time)
        self.unload_time = float(unload_time)
        self.return_time = float(return_time)
        self.maintenance_time = float(maintenance_time)

        self.pallet_info = pallet_info

        self.state: str = "idle"
        self.current_pallet: Optional[int] = None

    @property
    def idle(self) -> bool:
        return self.state == "idle"

    def start_trip(self, pallet_id: int, t: float) -> None:
        # Loading is instantaneous.
        self.state = "in_flight"
        self.current_pallet = pallet_id

        emit(
            t,
            "aircraft",
            "depart",
            {"aircraft_id": self.aircraft_id, "pallet_id": pallet_id},
        )

        delivery_time = t + self.flight_time + self.unload_time

        def _deliver() -> None:
            # Delivery occurs at end of unloading.
            info = self.pallet_info[pallet_id]
            latency = self.sim.now - info.gen_time
            emit(
                self.sim.now,
                "destination",
                "pallet_delivered",
                {
                    "pallet_id": pallet_id,
                    "aircraft_id": self.aircraft_id,
                    "latency": float(latency),
                },
            )

            return_complete_time = self.sim.now + self.return_time

            def _return_complete() -> None:
                emit(self.sim.now, "aircraft", "return", {"aircraft_id": self.aircraft_id})
                emit(
                    self.sim.now,
                    "aircraft",
                    "maintenance_start",
                    {"aircraft_id": self.aircraft_id},
                )
                self.state = "maintenance"

                maint_end_time = self.sim.now + self.maintenance_time

                def _maint_end() -> None:
                    emit(
                        self.sim.now,
                        "aircraft",
                        "maintenance_end",
                        {"aircraft_id": self.aircraft_id},
                    )
                    self.state = "idle"
                    self.current_pallet = None
                    # Coordinator may be able to assign immediately.
                    self.coordinator.schedule_try_assign(self.sim.now)

                self.sim.schedule(maint_end_time, priority=3, fn=_maint_end)

            self.sim.schedule(return_complete_time, priority=3, fn=_return_complete)

        self.sim.schedule(delivery_time, priority=3, fn=_deliver)


class Coordinator:
    def __init__(
        self,
        sim: Simulator,
        queue: LoadingQueue,
        aircraft: List[Aircraft],
        pallet_info: Dict[int, PalletInfo],
    ):
        self.sim = sim
        self.queue = queue
        self.aircraft = aircraft
        self.pallet_info = pallet_info

        self._try_assign_scheduled_at: Optional[float] = None

    def schedule_try_assign(self, t: float) -> None:
        """Debounced scheduling of the assignment attempt at time t.

        Uses a late priority so that expirations and enqueues at time t happen first.
        """
        t = float(t)
        if self._try_assign_scheduled_at == t:
            return
        self._try_assign_scheduled_at = t

        def _run() -> None:
            # Clear debounce marker (important if we schedule again at same time later).
            self._try_assign_scheduled_at = None
            self.try_assign(self.sim.now)

        self.sim.schedule(t, priority=5, fn=_run)

    def _get_idle_aircraft(self) -> Optional[Aircraft]:
        for ac in self.aircraft:
            if ac.idle:
                return ac
        return None

    def try_assign(self, t: float) -> None:
        # Assign as many pallets as possible at this same time.
        while len(self.queue) > 0:
            ac = self._get_idle_aircraft()
            if ac is None:
                return
            pallet_id, _exp = self.queue.dequeue_fifo()

            info = self.pallet_info[pallet_id]
            info.assigned = True

            emit(
                t,
                "coordinator",
                "assignment_created",
                {"aircraft_id": ac.aircraft_id, "pallet_id": pallet_id},
            )
            ac.start_trip(pallet_id=pallet_id, t=t)


class Facility:
    def __init__(
        self,
        sim: Simulator,
        queue: LoadingQueue,
        coordinator: Coordinator,
        pallet_interval: float,
        pallet_expiration_time: float,
        pallet_info: Dict[int, PalletInfo],
        stats: Dict[str, Any],
    ):
        self.sim = sim
        self.queue = queue
        self.coordinator = coordinator
        self.pallet_interval = float(pallet_interval)
        self.pallet_expiration_time = float(pallet_expiration_time)
        self.pallet_info = pallet_info
        self.stats = stats

        self._next_pallet_id = 1

    def schedule_first(self) -> None:
        self.sim.schedule(0.0, priority=1, fn=self._generate)

    def _generate(self) -> None:
        t = self.sim.now
        pallet_id = self._next_pallet_id
        self._next_pallet_id += 1

        expiration_time = t + self.pallet_expiration_time
        self.pallet_info[pallet_id] = PalletInfo(
            pallet_id=pallet_id, gen_time=t, expiration_time=expiration_time, assigned=False
        )

        emit(
            t,
            "facility",
            "pallet_generated",
            {"pallet_id": pallet_id, "expiration_time": float(expiration_time)},
        )

        self.queue.enqueue(pallet_id, expiration_time)
        emit(
            t,
            "queue",
            "pallet_queued",
            {"pallet_id": pallet_id, "queue_size": len(self.queue)},
        )

        # Schedule expiration (highest priority at that time).
        def _expire(pid: int = pallet_id) -> None:
            info = self.pallet_info.get(pid)
            # If it was assigned, deadline no longer matters.
            if info is None or info.assigned:
                return
            if self.queue.contains(pid):
                self.queue.remove(pid)
                self.stats["total_expired"] += 1
                emit(
                    self.sim.now,
                    "queue",
                    "pallet_expired",
                    {"pallet_id": pid, "total_expired": int(self.stats["total_expired"])},
                )
                # Expiration changes availability of cargo; allow immediate re-check.
                self.coordinator.schedule_try_assign(self.sim.now)

        if expiration_time <= self.sim.duration:
            self.sim.schedule(expiration_time, priority=0, fn=_expire)

        # Trigger assignment attempt after enqueue at same time.
        self.coordinator.schedule_try_assign(t)

        # Schedule next generation.
        next_t = t + self.pallet_interval
        if next_t <= self.sim.duration:
            self.sim.schedule(next_t, priority=1, fn=self._generate)


# ---------------------------------- CLI ------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
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


def _validate_args(a: argparse.Namespace) -> None:
    if a.duration < 0:
        raise SystemExit("--duration must be >= 0")
    if a.num_aircraft < 1:
        raise SystemExit("--num_aircraft must be >= 1")

    for name in (
        "pallet_interval",
        "pallet_expiration_time",
        "flight_time",
        "unload_time",
        "return_time",
        "maintenance_time",
    ):
        v = getattr(a, name)
        if v < 0:
            raise SystemExit(f"--{name} must be >= 0")

    # A zero pallet interval would create an infinite number of pallets at the
    # same simulation time.
    if a.pallet_interval <= 0:
        raise SystemExit("--pallet_interval must be > 0")

    # Practical guardrail to avoid pathological configurations that could violate
    # the "finish within 10 seconds wall-clock" requirement.
    # This does not affect simulation semantics; it prevents producing enormous
    # event logs.
    est_pallets = int(a.duration / a.pallet_interval) + 1
    if est_pallets > 50_000:
        raise SystemExit(
            "Configuration would generate too many pallets/events for this runner; "
            "increase --pallet_interval or reduce --duration."
        )


def main(argv: Optional[List[str]] = None) -> int:
    _configure_logging()
    args = parse_args(argv)
    _validate_args(args)


    sim = Simulator(duration=args.duration)

    pallet_info: Dict[int, PalletInfo] = {}
    stats: Dict[str, Any] = {"total_expired": 0}

    queue = LoadingQueue()

    # Create coordinator and aircraft.
    # Note: coordinator needs aircraft list; aircraft needs coordinator; create in two steps.
    coordinator = Coordinator(sim=sim, queue=queue, aircraft=[], pallet_info=pallet_info)

    aircraft: List[Aircraft] = []
    for i in range(1, args.num_aircraft + 1):
        aircraft.append(
            Aircraft(
                sim=sim,
                coordinator=coordinator,
                aircraft_id=i,
                flight_time=args.flight_time,
                unload_time=args.unload_time,
                return_time=args.return_time,
                maintenance_time=args.maintenance_time,
                pallet_info=pallet_info,
            )
        )
    coordinator.aircraft = aircraft

    facility = Facility(
        sim=sim,
        queue=queue,
        coordinator=coordinator,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
        pallet_info=pallet_info,
        stats=stats,
    )

    facility.schedule_first()

    sim.run()
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
