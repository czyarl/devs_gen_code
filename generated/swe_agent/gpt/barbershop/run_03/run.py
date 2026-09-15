#!/usr/bin/env python3
"""Barbershop discrete-event simulation.

Implements the workflow described in the PR description using SimPy.

STDIN: schedule lines `HH:MM:SS:mm newcust`
STDOUT: JSONL records (state/message)
STDERR: logs

Notes:
- The simulation consumes *all* stdin lines to build the initial schedule before starting.
- The simulation clock starts at 0.0; input times are normalized by subtracting the earliest input timestamp.
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


def emit(obj: dict) -> None:
    """Emit a single JSONL object to stdout."""
    sys.stdout.write(json.dumps(obj) + "\n")


def parse_time_to_seconds(ts: str) -> float:
    """Parse `HH:MM:SS:mm`.

    The last component is named `mm` in the spec; it may appear as 2 digits (centiseconds)
    or 3 digits (milliseconds) depending on test data.
    """

    parts = ts.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {ts!r}")
    hh, mm, ss, frac = parts

    h = int(hh)
    m = int(mm)
    s = int(ss)
    frac_i = int(frac)

    if len(frac) <= 2:
        frac_s = frac_i / 100.0
    else:
        frac_s = frac_i / 1000.0

    return h * 3600.0 + m * 60.0 + s + frac_s


def read_schedule(stdin) -> List[Tuple[float, str]]:
    """Consume ALL stdin lines and return a sorted, normalized schedule."""

    events: List[Tuple[float, str]] = []
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            raise ValueError(f"Invalid schedule line: {line!r}")
        ts, name = parts
        if name != "newcust":
            raise ValueError(f"Unsupported event name: {name!r}")
        events.append((parse_time_to_seconds(ts), name))

    if not events:
        return []

    t0 = min(t for t, _ in events)
    normalized = [(t - t0, n) for t, n in events]
    normalized.sort(key=lambda x: x[0])
    return normalized


@dataclass(frozen=True)
class Customer:
    id: int


class Reception:
    """Reception desk.

    - Waiting-area capacity is strictly 8 customers.
    - Processes 1 customer at a time, 5 seconds check-in time.
    - After check-in, the receptionist waits until `checkhair` is available before handing off.

    Tracked state:
    - `total customers num` == number of customers currently in the reception waiting area
      (including the one being checked in).
    """

    def __init__(
        self,
        env: simpy.Environment,
        *,
        out_to_checkhair: simpy.Store,
        done_from_checkhair: simpy.Store,
        wait_checkhair_available,
        reserve_checkhair,
    ):
        self.env = env
        self.out_to_checkhair = out_to_checkhair
        self.done_from_checkhair = done_from_checkhair
        self.wait_checkhair_available = wait_checkhair_available
        self.reserve_checkhair = reserve_checkhair

        self.waiting: Deque[Customer] = deque()
        self.capacity_total = 8

        # tracked state
        self.total_customers_num = 0

        self._new_arrival_event = simpy.Event(env)

        env.process(self._service_loop())
        env.process(self._drain_done_loop())

    def _signal_new_arrival(self) -> None:
        if not self._new_arrival_event.triggered:
            self._new_arrival_event.succeed()
        self._new_arrival_event = simpy.Event(self.env)

    def _emit_total_customers(self) -> None:
        emit(
            {
                "time": float(self.env.now),
                "type": "state",
                "model": "reception",
                "field": "total customers num",
                "value": self.total_customers_num,
            }
        )

    def arrive(self, customer: Customer) -> None:
        # Capacity check is for the waiting-area queue.
        if self.total_customers_num >= self.capacity_total:
            return

        self.waiting.append(customer)
        self.total_customers_num += 1
        self._emit_total_customers()

        self._signal_new_arrival()

    def _drain_done_loop(self):
        """Drain completion notifications to avoid unbounded buffering.

        The spec requires the message from checkhair->reception to be emitted by the sender;
        reception doesn't need to emit anything additional.
        """

        while True:
            _ = yield self.done_from_checkhair.get()

    def _service_loop(self):
        while True:
            if not self.waiting:
                yield self._new_arrival_event
                continue

            cust = self.waiting[0]

            # Process (check-in). Customer remains in queue.
            yield self.env.timeout(5.0)

            # Handoff: wait until checkhair is available.
            yield self.wait_checkhair_available()
            self.reserve_checkhair()

            yield self.out_to_checkhair.put(cust)
            emit(
                {
                    "time": float(self.env.now),
                    "type": "message",
                    "model": "reception",
                    "port": "cust",
                    "content": "newcust",
                }
            )

            # Customer leaves the waiting area.
            self.waiting.popleft()
            self.total_customers_num -= 1
            self._emit_total_customers()


class Availability:
    """A small helper to model the checkhair availability handshake.

    Reception needs to *wait until checkhair is available* and then *reserve it* so no other
    handoff can happen until checkhair marks itself available again.

    Implemented as a shared, replaceable SimPy event.
    """

    def __init__(self, env: simpy.Environment):
        self.env = env
        self._event = simpy.Event(env)
        # Initially available at t=0.0
        self._event.succeed()

    def wait_available(self):
        return self._event

    def reserve(self) -> None:
        # Replace with a new, un-triggered event => now unavailable.
        self._event = simpy.Event(self.env)

    def mark_available(self) -> None:
        if not self._event.triggered:
            self._event.succeed()


class CheckHair:
    """Hair inspection phase.

    Processing is strictly sequential:
    1) Receive from reception (only when available)
    2) Inspect for 7s
    3) Forward to cutter
    4) Wait for cutter's done signal
    5) Notify reception that full service is complete
    6) Become available again

    Tracked state:
    - field `customer` is `newcust` when inspection starts, and `done` after cutter finishes.
    """

    def __init__(
        self,
        env: simpy.Environment,
        *,
        in_from_reception: simpy.Store,
        to_cut: simpy.Store,
        done_from_cut: simpy.Store,
        to_reception: simpy.Store,
        availability: Availability,
    ):
        self.env = env
        self.in_from_reception = in_from_reception
        self.to_cut = to_cut
        self.done_from_cut = done_from_cut
        self.to_reception = to_reception
        self.availability = availability

        env.process(self._run())

    def _run(self):
        while True:
            cust: Customer = yield self.in_from_reception.get()

            emit(
                {
                    "time": float(self.env.now),
                    "type": "state",
                    "model": "checkhair",
                    "field": "customer",
                    "value": "newcust",
                }
            )

            yield self.env.timeout(7.0)

            yield self.to_cut.put(cust)
            emit(
                {
                    "time": float(self.env.now),
                    "type": "message",
                    "model": "checkhair",
                    "port": "to_cut",
                    "content": "newcust",
                }
            )

            done_msg = yield self.done_from_cut.get()
            if done_msg != "done":
                # ignore unexpected messages
                continue

            emit(
                {
                    "time": float(self.env.now),
                    "type": "state",
                    "model": "checkhair",
                    "field": "customer",
                    "value": "done",
                }
            )

            # Notify reception; only after this does checkhair become available again.
            yield self.to_reception.put("done")
            emit(
                {
                    "time": float(self.env.now),
                    "type": "message",
                    "model": "checkhair",
                    "port": "to_reception",
                    "content": "done",
                }
            )

            self.availability.mark_available()


class CutHair:
    """Cutting (20s) and signals done."""

    def __init__(
        self,
        env: simpy.Environment,
        *,
        in_from_checkhair: simpy.Store,
        out_to_checkhair: simpy.Store,
    ):
        self.env = env
        self.in_from_checkhair = in_from_checkhair
        self.out_to_checkhair = out_to_checkhair

        self.total_customer_done = 0

        env.process(self._run())

    def _run(self):
        while True:
            _cust: Customer = yield self.in_from_checkhair.get()

            yield self.env.timeout(20.0)

            self.total_customer_done += 1
            emit(
                {
                    "time": float(self.env.now),
                    "type": "state",
                    "model": "cuthair",
                    "field": "total customer done",
                    "value": self.total_customer_done,
                }
            )

            yield self.out_to_checkhair.put("done")
            emit(
                {
                    "time": float(self.env.now),
                    "type": "message",
                    "model": "cuthair",
                    "port": "out",
                    "content": "done",
                }
            )


def build_and_run(schedule: List[Tuple[float, str]], simulation_time: float) -> None:
    env = simpy.Environment(initial_time=0.0)

    # Communication channels.
    reception_to_checkhair = simpy.Store(env)  # actual handoff occurs only when checkhair is reserved/available
    checkhair_to_cuthair = simpy.Store(env, capacity=1)
    cuthair_to_checkhair = simpy.Store(env, capacity=1)
    checkhair_to_reception = simpy.Store(env)  # drain-only by reception

    availability = Availability(env)

    reception = Reception(
        env,
        out_to_checkhair=reception_to_checkhair,
        done_from_checkhair=checkhair_to_reception,
        wait_checkhair_available=availability.wait_available,
        reserve_checkhair=availability.reserve,
    )

    _ = CheckHair(
        env,
        in_from_reception=reception_to_checkhair,
        to_cut=checkhair_to_cuthair,
        done_from_cut=cuthair_to_checkhair,
        to_reception=checkhair_to_reception,
        availability=availability,
    )

    _ = CutHair(env, in_from_checkhair=checkhair_to_cuthair, out_to_checkhair=cuthair_to_checkhair)

    def arrival_process(at: float, cid: int):
        yield env.timeout(at)
        reception.arrive(Customer(cid))

    for i, (t, name) in enumerate(schedule, start=1):
        if name == "newcust":
            env.process(arrival_process(float(t), i))

    env.run(until=float(simulation_time))


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(levelname)s:%(message)s")

    try:
        schedule = read_schedule(sys.stdin)
    except Exception as e:
        logging.error(str(e))
        return 2

    build_and_run(schedule, args.simulation_time)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
