#!/usr/bin/env python3
"""Barbershop discrete-event simulation.

Entry point: python run.py

Reads a schedule from stdin (one event per line) BEFORE starting the simulation.
Emits JSONL records to stdout.

Only JSON objects are printed to stdout; any diagnostics must go to stderr.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from dataclasses import dataclass
from typing import Deque, List

import simpy




def _parse_time_to_seconds(token: str) -> float:
    """Parse HH:MM:SS:mm into seconds as float.

    The last component ("mm") is interpreted as centiseconds (1/100 second).
    """

    parts = token.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {token!r}")
    hh, mm, ss, cs = (int(p) for p in parts)
    return hh * 3600.0 + mm * 60.0 + ss + cs / 100.0


class JsonlEmitter:
    def __init__(self, out_stream):
        self._out = out_stream

    def emit(self, obj: dict) -> None:
        self._out.write(json.dumps(obj) + "\n")


def emit_state(emitter: JsonlEmitter, time: float, model: str, field: str, value) -> None:
    emitter.emit(
        {
            "time": float(time),
            "type": "state",
            "model": model,
            "field": field,
            "value": value,
        }
    )


def emit_message(emitter: JsonlEmitter, time: float, model: str, port: str, content: str) -> None:
    emitter.emit(
        {
            "time": float(time),
            "type": "message",
            "model": model,
            "port": port,
            "content": content,
        }
    )


@dataclass(frozen=True)
class ScheduleEvent:
    time: float
    name: str


class Cuthair:
    """Hair cutting phase."""

    def __init__(self, env: simpy.Environment, emitter: JsonlEmitter):
        self.env = env
        self.emitter = emitter
        self.total_done = 0

    def cut(self):
        # Hold customer for exactly 20 seconds.
        yield self.env.timeout(20.0)
        self.total_done += 1
        emit_state(self.emitter, self.env.now, "cuthair", "total customer done", self.total_done)
        emit_message(self.emitter, self.env.now, "cuthair", "out", "done")


class Checkhair:
    """Hair inspection/coordination phase."""

    def __init__(self, env: simpy.Environment, emitter: JsonlEmitter, cuthair: Cuthair):
        self.env = env
        self.emitter = emitter
        self.cuthair = cuthair

    def handle_customer(self):
        # Receive: accept customer from reception.
        emit_state(self.emitter, self.env.now, "checkhair", "customer", "newcust")

        # Process: 7 seconds.
        yield self.env.timeout(7.0)

        # Forward to cutting.
        emit_message(self.emitter, self.env.now, "checkhair", "to_cut", "newcust")

        # Wait for a "done" signal from cutting phase.
        yield self.env.process(self.cuthair.cut())

        # Completion: notify reception and become available again.
        emit_state(self.emitter, self.env.now, "checkhair", "customer", "done")
        emit_message(self.emitter, self.env.now, "checkhair", "to_reception", "done")


class Reception:
    """Reception desk with 8-person waiting area and 5s check-in.

    Important: per requirements, reception processes ONE customer at a time for
    5 seconds, and after that it must *wait* until checkhair is available to
    hand the customer off. Only after the handoff occurs does reception start
    processing the next customer in the queue.
    """

    def __init__(
        self,
        env: simpy.Environment,
        emitter: JsonlEmitter,
        barber_lock: simpy.Resource,
        checkhair: Checkhair,
    ):
        self.env = env
        self.emitter = emitter
        self.barber_lock = barber_lock
        self.checkhair = checkhair

        # Waiting area occupancy (includes customers being checked-in and those waiting for barber).
        self.total_customers_num = 0

        # FIFO of customers in the reception waiting area.
        self._queue: Deque[str] = deque()

        # Event to wake reception worker when a new customer arrives.
        self._arrival_event = env.event()

        env.process(self._worker())

    def _pulse_arrival(self) -> None:
        if not self._arrival_event.triggered:
            self._arrival_event.succeed()
        self._arrival_event = self.env.event()

    def arrive(self, customer: str = "newcust") -> None:
        # Arrival: check waiting area capacity.
        if self.total_customers_num >= 8:
            return
        self.total_customers_num += 1
        emit_state(
            self.emitter,
            self.env.now,
            "reception",
            "total customers num",
            self.total_customers_num,
        )
        self._queue.append(customer)
        self._pulse_arrival()

    def _worker(self):
        while True:
            # Wait for at least one customer.
            while not self._queue:
                yield self._arrival_event

            # Process the first customer in the queue for exactly 5 seconds.
            yield self.env.timeout(5.0)

            # After 5 seconds, attempt to handoff. If barber isn't available,
            # we must keep waiting (without starting the next check-in).
            with self.barber_lock.request() as req:
                yield req

                # Customer is still in the reception queue until now.
                self._queue.popleft()

                self.total_customers_num -= 1
                emit_state(
                    self.emitter,
                    self.env.now,
                    "reception",
                    "total customers num",
                    self.total_customers_num,
                )
                emit_message(self.emitter, self.env.now, "reception", "cust", "newcust")

                # Hold the barber lock until full service complete.
                yield self.env.process(self.checkhair.handle_customer())


def read_schedule_from_stdin(stdin) -> List[ScheduleEvent]:
    events: List[ScheduleEvent] = []
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            raise ValueError(f"Invalid schedule line: {raw!r}")
        t_str, name = parts
        if name != "newcust":
            raise ValueError(f"Unsupported event name: {name!r}")
        t = _parse_time_to_seconds(t_str)
        events.append(ScheduleEvent(time=t, name=name))
    events.sort(key=lambda e: e.time)
    return events


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Barbershop simulation")
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=1000000.0,
        help="Total simulation time in seconds.",
    )
    args = parser.parse_args(argv)

    # MUST consume ALL input lines before starting simulation.
    schedule = read_schedule_from_stdin(sys.stdin)

    env = simpy.Environment(initial_time=0.0)
    emitter = JsonlEmitter(sys.stdout)

    barber_lock = simpy.Resource(env, capacity=1)
    cuthair = Cuthair(env, emitter)
    checkhair = Checkhair(env, emitter, cuthair)
    _reception = Reception(env, emitter, barber_lock, checkhair)

    def _arrival_at(t: float):
        # Schedule an arrival at absolute simulation time t.
        delay = max(0.0, t - env.now)
        yield env.timeout(delay)
        _reception.arrive("newcust")

    for ev in schedule:
        env.process(_arrival_at(ev.time))

    sim_time = float(args.simulation_time)
    if sim_time < 0:
        raise ValueError("--simulation_time must be non-negative")

    env.run(until=sim_time)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
