#!/usr/bin/env python3
"""Barbershop discrete-event simulation.

Implements the workflow described in the PR requirements using SimPy.

STDIN: schedule lines of the form `HH:MM:SS:mm newcust`
STDOUT: JSONL of state/message events
STDERR: debug logs
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Tuple

import simpy


LOGGER = logging.getLogger("barbershop")


def parse_time_to_seconds(token: str) -> float:
    """Parse `HH:MM:SS:mm` into seconds.

    `mm` is interpreted as centiseconds.
    """
    parts = token.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"invalid time format: {token!r}")
    hh, mm, ss, cs = (int(p) for p in parts)
    if not (0 <= mm < 60 and 0 <= ss < 60 and 0 <= cs < 100 and hh >= 0):
        raise ValueError(f"invalid time values: {token!r}")
    return hh * 3600 + mm * 60 + ss + cs / 100.0


def emit(obj: dict) -> None:
    """Emit one JSONL object to stdout."""
    sys.stdout.write(json.dumps(obj) + "\n")


def emit_state(time: float, model: str, field: str, value) -> None:
    emit({"time": float(time), "type": "state", "model": model, "field": field, "value": value})


def emit_message(time: float, model: str, port: str, content: str) -> None:
    emit({"time": float(time), "type": "message", "model": model, "port": port, "content": content})


@dataclass
class Customer:
    # We keep an internal id for debugging, but it is never emitted.
    cid: int


class CutHair:
    """Hair cutting module."""

    def __init__(self, env: simpy.Environment):
        self.env = env
        self.inbox: simpy.Store[Customer] = simpy.Store(env)
        self.done_out: simpy.Store[str] = simpy.Store(env)
        self.total_done: int = 0
        self.env.process(self._run())

    def _run(self):
        while True:
            cust: Customer = yield self.inbox.get()
            # Process
            yield self.env.timeout(20.0)
            # Completion
            self.total_done += 1
            emit_state(self.env.now, "cuthair", "total customer done", self.total_done)
            emit_message(self.env.now, "cuthair", "out", "done")
            yield self.done_out.put("done")


class CheckHair:
    """Hair inspection module and coordinator."""

    def __init__(self, env: simpy.Environment, cutter: CutHair):
        self.env = env
        self.cutter = cutter
        self.inbox: simpy.Store[Customer] = simpy.Store(env)

        self._available: bool = True
        self._available_event: simpy.Event = env.event()
        self._available_event.succeed()  # initially available

        self.env.process(self._run())

    @property
    def available_event(self) -> simpy.Event:
        return self._available_event

    @property
    def is_available(self) -> bool:
        return self._available

    def _set_busy(self):
        self._available = False
        # Create a new event that will be succeeded when we become available.
        self._available_event = self.env.event()

    def _set_available(self):
        self._available = True
        if not self._available_event.triggered:
            self._available_event.succeed()

    def _run(self):
        while True:
            cust: Customer = yield self.inbox.get()
            self._set_busy()

            # Inspection begins
            emit_state(self.env.now, "checkhair", "customer", "newcust")
            yield self.env.timeout(7.0)

            # Forward to cutting
            emit_message(self.env.now, "checkhair", "to_cut", "newcust")
            yield self.cutter.inbox.put(cust)

            # Wait for cutting completion
            done_signal: str = yield self.cutter.done_out.get()
            if done_signal != "done":
                LOGGER.warning("unexpected done signal: %r", done_signal)

            emit_state(self.env.now, "checkhair", "customer", "done")
            emit_message(self.env.now, "checkhair", "to_reception", "done")
            self._set_available()


class Reception:
    """Reception desk and waiting area.

    Requirements:
    - Waiting area capacity is 8.
    - Processes exactly 1 customer at a time, taking 5 seconds per customer.
    - After 5 seconds, waits until `checkhair` is available to handoff.
    - Only after successful handoff does it start processing the next customer.
    """

    def __init__(self, env: simpy.Environment, inspector: CheckHair):
        self.env = env
        self.inspector = inspector

        self.capacity: int = 8
        self.total_customers_num: int = 0

        self._queue: Deque[Customer] = deque()
        self._arrival_event: simpy.Event = env.event()

        self.env.process(self._worker())

    def arrive(self, cust: Customer) -> None:
        # Arrival: accept iff queue size < 8.
        if self.total_customers_num >= self.capacity:
            return

        self.total_customers_num += 1
        emit_state(self.env.now, "reception", "total customers num", self.total_customers_num)

        self._queue.append(cust)
        if not self._arrival_event.triggered:
            self._arrival_event.succeed()

    def _worker(self):
        while True:
            while not self._queue:
                self._arrival_event = self.env.event()
                yield self._arrival_event

            # The customer remains in the reception queue while being checked in.
            cust = self._queue[0]
            yield self.env.timeout(5.0)

            # After 5 seconds, handoff only if checkhair is available;
            # otherwise block until it becomes available.
            if not self.inspector.is_available:
                yield self.inspector.available_event

            emit_message(self.env.now, "reception", "cust", "newcust")
            yield self.inspector.inbox.put(cust)

            # Remove from queue only after sending.
            self._queue.popleft()
            self.total_customers_num -= 1
            emit_state(self.env.now, "reception", "total customers num", self.total_customers_num)
    
    


def read_schedule_from_stdin() -> List[Tuple[float, str]]:
    """Read and parse all stdin lines before simulation starts."""
    events: List[Tuple[float, str]] = []
    for idx, raw in enumerate(sys.stdin.read().splitlines()):
        line = raw.strip()
        if not line:
            continue
        try:
            time_token, name = line.split(maxsplit=1)
        except ValueError:
            LOGGER.warning("ignoring invalid schedule line %d: %r", idx + 1, raw)
            continue
        if name.strip() != "newcust":
            LOGGER.warning("ignoring unsupported event %r on line %d", name, idx + 1)
            continue
        try:
            t = parse_time_to_seconds(time_token)
        except ValueError as e:
            LOGGER.warning("ignoring invalid time on line %d: %s", idx + 1, e)
            continue
        events.append((t, "newcust"))

    # Stable sort to preserve input order for same timestamps.
    events.sort(key=lambda x: x[0])

    # Normalize so simulation clock starts at 0.0 (first scheduled event occurs at t=0).
    if events:
        t0 = events[0][0]
        if t0 != 0.0:
            events = [(t - t0, name) for t, name in events]

    return events


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Barbershop discrete-event simulation")
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=1000000.0,
        help="Total simulation time in seconds (default: 1000000.0)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
        stream=sys.stderr,
    )

    schedule = read_schedule_from_stdin()

    env = simpy.Environment(initial_time=0.0)

    cutter = CutHair(env)
    inspector = CheckHair(env, cutter)
    reception = Reception(env, inspector)

    # Build initial event schedule (create all arrival processes) before running the env.
    next_cid = 1

    def arrival_proc(at_time: float, cust: Customer):
        delay = max(0.0, at_time - env.now)
        if delay:
            yield env.timeout(delay)
        reception.arrive(cust)

    for t, _name in schedule:
        cust = Customer(cid=next_cid)
        next_cid += 1
        env.process(arrival_proc(t, cust))

    env.run(until=float(args.simulation_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
