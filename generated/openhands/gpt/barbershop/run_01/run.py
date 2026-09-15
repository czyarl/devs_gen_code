#!/usr/bin/env python3
"""Barbershop discrete-event simulation.

Reads a schedule of arrival events from STDIN (one per line) BEFORE starting
simulation, then runs a SimPy-based DES model.

STDOUT: JSONL records for state changes and inter-module messages.
STDERR: logs/debug.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import deque
from typing import Deque, Iterable, List, Optional

import simpy


def parse_time_hhmmssmm(token: str) -> float:
    """Parse `HH:MM:SS:mm` into seconds as float.

    The final `mm` is interpreted as hundredths of a second (00-99).
    """
    parts = token.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid time token: {token!r}")
    hh, mm, ss, hs = (int(p) for p in parts)
    if hh < 0 or mm < 0 or ss < 0 or hs < 0:
        raise ValueError(f"Negative time component in: {token!r}")
    return hh * 3600.0 + mm * 60.0 + ss * 1.0 + hs / 100.0


def emit(obj: dict) -> None:
    # Only JSONL on stdout.
    sys.stdout.write(json.dumps(obj) + "\n")


def emit_state(time: float, model: str, field: str, value) -> None:
    emit({"time": float(time), "type": "state", "model": model, "field": field, "value": value})


def emit_message(time: float, model: str, port: str, content: str) -> None:
    emit({"time": float(time), "type": "message", "model": model, "port": port, "content": content})


class CutHair:
    """Hair Cutting Phase (cuthair)."""

    def __init__(self, env: simpy.Environment):
        self.env = env
        self.inbox: simpy.Store = simpy.Store(env)
        self.total_done: int = 0
        self._checkhair_done_in: Optional[simpy.Store] = None
        self._proc = env.process(self.run())

    def bind_checkhair_done_in(self, done_in: simpy.Store) -> None:
        self._checkhair_done_in = done_in

    def run(self):
        while True:
            _cust = yield self.inbox.get()  # content is always "newcust"
            yield self.env.timeout(20.0)

            self.total_done += 1
            emit_state(self.env.now, "cuthair", "total customer done", self.total_done)

            emit_message(self.env.now, "cuthair", "out", "done")
            if self._checkhair_done_in is not None:
                self._checkhair_done_in.put("done")


class CheckHair:
    """Hair Inspection Phase (checkhair)."""

    def __init__(self, env: simpy.Environment, cuthair: CutHair):
        self.env = env
        self.cuthair = cuthair
        self.inbox: simpy.Store = simpy.Store(env)
        self.done_in: simpy.Store = simpy.Store(env)

        # Availability event: succeeded => available. When busy, replaced by a new, pending event.
        self.ready: simpy.Event = env.event()
        self.ready.succeed()  # initially available

        self._proc = env.process(self.run())

    def run(self):
        while True:
            _cust = yield self.inbox.get()  # content is always "newcust"

            # Become busy: reset readiness.
            self.ready = self.env.event()

            emit_state(self.env.now, "checkhair", "customer", "newcust")
            yield self.env.timeout(7.0)

            emit_message(self.env.now, "checkhair", "to_cut", "newcust")
            self.cuthair.inbox.put("newcust")

            _done = yield self.done_in.get()  # expected "done"
            emit_state(self.env.now, "checkhair", "customer", "done")
            emit_message(self.env.now, "checkhair", "to_reception", "done")

            # Become available again.
            self.ready.succeed()


class Reception:
    """Reception Desk (reception)."""

    def __init__(self, env: simpy.Environment, checkhair: CheckHair):
        self.env = env
        self.checkhair = checkhair
        self.queue: Deque[str] = deque()

        self._wakeup: simpy.Event = env.event()  # triggered when a new customer arrives to an empty queue
        self._busy: bool = False  # internal server is processing a customer or blocked on handoff

        self._proc = env.process(self.run())

    def arrival(self, cust: str = "newcust") -> None:
        """Handle a new customer arrival."""
        if len(self.queue) >= 8:
            return
        self.queue.append(cust)
        emit_state(self.env.now, "reception", "total customers num", len(self.queue))

        # Wake the server if it was waiting on an empty queue.
        if not self._wakeup.triggered:
            self._wakeup.succeed()

    def run(self):
        while True:
            if not self.queue:
                # Wait for next arrival.
                self._wakeup = self.env.event()
                yield self._wakeup

            # Process the first customer (still stays in queue during check-in).
            self._busy = True
            yield self.env.timeout(5.0)

            # Handoff gating: if checkhair is not available, block here.
            yield self.checkhair.ready

            # Send to checkhair.
            emit_message(self.env.now, "reception", "cust", "newcust")
            self.queue.popleft()
            emit_state(self.env.now, "reception", "total customers num", len(self.queue))
            self.checkhair.inbox.put("newcust")

            self._busy = False


def read_schedule(stdin: Iterable[str], logger: logging.Logger) -> List[float]:
    """Read ALL stdin lines and return sorted arrival times (seconds).

    The simulation clock starts at 0.0, so if the schedule uses an absolute
    HH:MM:SS:mm clock (e.g., 08:00:00:00), we normalize by subtracting the
    earliest timestamp.
    """
    arrivals_abs: List[float] = []
    for lineno, raw in enumerate(stdin, start=1):
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            logger.warning("Ignoring malformed line %d: %r", lineno, line)
            continue
        time_tok, event = parts
        if event != "newcust":
            logger.warning("Ignoring unknown event on line %d: %r", lineno, line)
            continue
        try:
            t = parse_time_hhmmssmm(time_tok)
        except Exception as e:
            logger.warning("Ignoring bad time on line %d: %r (%s)", lineno, line, e)
            continue
        arrivals_abs.append(float(max(0.0, t)))

    if not arrivals_abs:
        return []

    arrivals_abs.sort()
    t0 = arrivals_abs[0]
    if t0 != 0.0:
        logger.info("Normalizing schedule by subtracting start time %.2f", t0)

    return [t - t0 for t in arrivals_abs]


def arrival_process(env: simpy.Environment, reception: Reception, arrivals: List[float]):
    for t in arrivals:
        if t > env.now:
            yield env.timeout(t - env.now)
        reception.arrival("newcust")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Barbershop DES simulation")
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=1000000.0,
        help="Total simulation time in seconds (default: 1000000.0)",
    )
    args = parser.parse_args(argv)

    # Keep stdout strictly for JSONL records; use stderr for any logs.
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(levelname)s:%(message)s")
    logger = logging.getLogger("barbershop")

    # IMPORTANT: consume ALL stdin before creating/running the simulation.
    arrivals = read_schedule(sys.stdin, logger)
    logger.info("Read %d arrival events", len(arrivals))

    env = simpy.Environment()

    cuthair = CutHair(env)
    checkhair = CheckHair(env, cuthair)
    cuthair.bind_checkhair_done_in(checkhair.done_in)
    reception = Reception(env, checkhair)

    env.process(arrival_process(env, reception, arrivals))

    # Run the event-based simulation up to the requested horizon.
    # SimPy will not iterate over empty time; runtime is proportional to event count.
    env.run(until=float(args.simulation_time))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
