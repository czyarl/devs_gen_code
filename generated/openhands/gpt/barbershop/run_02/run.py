#!/usr/bin/env python3
"""Discrete-event simulation of a barbershop workflow.

Requirements implemented:
- Python 3.10+
- CLI via argparse
- Input schedule fully read from stdin before simulation starts
- Simulation via simpy (DES)
- Output only JSONL to stdout; any logs go to stderr
"""

import argparse
import json
import logging
import sys
from collections import deque

import simpy


def parse_time_hhmmssmm(token: str) -> float:
    """Parse HH:MM:SS:mm into seconds (float).

    The last component is interpreted as a fractional second with precision
    based on its digit length (e.g., 2 digits => centiseconds).
    """
    parts = token.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid time token (expected HH:MM:SS:mm): {token!r}")
    hh_s, mm_s, ss_s, frac_s = parts
    hh = int(hh_s)
    mm = int(mm_s)
    ss = int(ss_s)

    frac_digits = len(frac_s)
    if frac_digits <= 0:
        frac = 0.0
    else:
        frac_int = int(frac_s)
        frac = frac_int / (10**frac_digits)

    return hh * 3600.0 + mm * 60.0 + ss + frac


def emit(obj: dict) -> None:
    """Write exactly one JSON object line to stdout."""
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")


class Customer:
    def __init__(self, kind: str = "newcust"):
        self.kind = kind


class TerminationController:
    def __init__(self, env: simpy.Environment):
        self.env = env
        self.sim_done = env.event()
        self.arrivals_done = False
        self.reception = None
        self.checkhair = None
        self.cuthair = None

    def maybe_finish(self) -> None:
        if self.sim_done.triggered:
            return
        if not self.arrivals_done:
            return
        if self.reception is None or self.checkhair is None or self.cuthair is None:
            return

        if (
            self.reception.is_idle()
            and self.checkhair.is_idle()
            and self.cuthair.is_idle()
        ):
            self.sim_done.succeed()


class Reception:
    """Reception desk with a finite waiting area and single-server check-in."""

    def __init__(
        self,
        env: simpy.Environment,
        term: TerminationController,
        checkhair: "CheckHair",
        capacity: int = 8,
        checkin_time: float = 5.0,
        name: str = "reception",
    ):
        self.env = env
        self.term = term
        self.checkhair = checkhair
        self.capacity = capacity
        self.checkin_time = checkin_time
        self.name = name

        self.queue = deque()
        self._idle = True
        self._arrival_event = env.event()

    def is_idle(self) -> bool:
        # Idle only when no queued customers and not processing.
        return self._idle and (len(self.queue) == 0)

    def _set_idle(self, value: bool) -> None:
        self._idle = value

    def arrive(self, cust: Customer) -> None:
        """Handle an external arrival event."""
        if len(self.queue) >= self.capacity:
            # Ignore new customer when waiting area is full.
            return

        was_empty = (len(self.queue) == 0)
        self.queue.append(cust)
        emit(
            {
                "time": float(self.env.now),
                "type": "state",
                "model": self.name,
                "field": "total customers num",
                "value": int(len(self.queue)),
            }
        )

        if was_empty and not self._arrival_event.triggered:
            self._arrival_event.succeed()

        self.term.maybe_finish()

    def notify_service_complete(self) -> None:
        # Currently, reception does not change internal tracked state on completion,
        # but this callback provides a hook for termination checks.
        self.term.maybe_finish()

    def run(self) -> simpy.events.Event:
        while True:
            if not self.queue:
                self._set_idle(True)
                # Wait for at least one arrival (or forever).
                self._arrival_event = self.env.event()
                self.term.maybe_finish()
                yield self._arrival_event
                continue

            self._set_idle(False)
            # Process the first customer (still remains in queue during check-in).
            yield self.env.timeout(self.checkin_time)

            # After check-in, wait until checkhair is available, then handoff.
            yield self.checkhair.when_available()

            # Send the customer out (now leaves the queue).
            self.queue.popleft()
            emit(
                {
                    "time": float(self.env.now),
                    "type": "state",
                    "model": self.name,
                    "field": "total customers num",
                    "value": int(len(self.queue)),
                }
            )
            emit(
                {
                    "time": float(self.env.now),
                    "type": "message",
                    "model": self.name,
                    "port": "cust",
                    "content": "newcust",
                }
            )

            self.checkhair.accept(Customer("newcust"))
            self.term.maybe_finish()


class CheckHair:
    """Hair inspection/consultation module coordinating with hair cutting."""

    def __init__(
        self,
        env: simpy.Environment,
        term: TerminationController,
        cuthair: "CutHair",
        reception = None,
        consult_time: float = 7.0,
        name: str = "checkhair",
    ):
        self.env = env
        self.term = term
        self.cuthair = cuthair
        self.reception = reception
        self.consult_time = consult_time
        self.name = name

        self.inbox = simpy.Store(env)
        self.done_inbox = simpy.Store(env)

        self._available_evt = env.event()
        self._available = True
        # Start as available.
        self._available_evt.succeed()

        self._busy = False

    def is_idle(self) -> bool:
        # Idle when available and no queued messages.
        return self._available and (len(self.inbox.items) == 0) and (len(self.done_inbox.items) == 0) and not self._busy

    def when_available(self) -> simpy.events.Event:
        return self._available_evt

    def accept(self, cust: Customer) -> None:
        self.inbox.put(cust)

    def _set_available(self, value: bool) -> None:
        self._available = value
        if value:
            if not self._available_evt.triggered:
                self._available_evt.succeed()
        else:
            # Create a fresh event to wait on.
            self._available_evt = self.env.event()

    def run(self) -> simpy.events.Event:
        while True:
            cust = yield self.inbox.get()
            # Transition to busy (unavailable).
            self._busy = True
            self._set_available(False)

            emit(
                {
                    "time": float(self.env.now),
                    "type": "state",
                    "model": self.name,
                    "field": "customer",
                    "value": "newcust",
                }
            )

            # Consultation
            yield self.env.timeout(self.consult_time)

            # Forward to cutting
            emit(
                {
                    "time": float(self.env.now),
                    "type": "message",
                    "model": self.name,
                    "port": "to_cut",
                    "content": "newcust",
                }
            )
            self.cuthair.accept(cust)

            # Wait for done signal from cutting
            _ = yield self.done_inbox.get()

            emit(
                {
                    "time": float(self.env.now),
                    "type": "state",
                    "model": self.name,
                    "field": "customer",
                    "value": "done",
                }
            )
            emit(
                {
                    "time": float(self.env.now),
                    "type": "message",
                    "model": self.name,
                    "port": "to_reception",
                    "content": "done",
                }
            )
            if self.reception is not None:
                self.reception.notify_service_complete()

            # Now becomes available again.
            self._busy = False
            self._set_available(True)
            self.term.maybe_finish()


class CutHair:
    """Hair cutting module."""

    def __init__(
        self,
        env: simpy.Environment,
        term: TerminationController,
        checkhair = None,
        cut_time: float = 20.0,
        name: str = "cuthair",
    ):
        self.env = env
        self.term = term
        self.checkhair = checkhair
        self.cut_time = cut_time
        self.name = name

        self.inbox = simpy.Store(env)
        self.total_done = 0
        self._busy = False

    def is_idle(self) -> bool:
        return (not self._busy) and (len(self.inbox.items) == 0)

    def accept(self, cust: Customer) -> None:
        self.inbox.put(cust)

    def run(self) -> simpy.events.Event:
        while True:
            cust = yield self.inbox.get()
            self._busy = True
            yield self.env.timeout(self.cut_time)

            self.total_done += 1
            emit(
                {
                    "time": float(self.env.now),
                    "type": "state",
                    "model": self.name,
                    "field": "total customer done",
                    "value": int(self.total_done),
                }
            )
            emit(
                {
                    "time": float(self.env.now),
                    "type": "message",
                    "model": self.name,
                    "port": "out",
                    "content": "done",
                }
            )

            if self.checkhair is not None:
                self.checkhair.done_inbox.put("done")

            self._busy = False
            self.term.maybe_finish()


def read_schedule_from_stdin(stdin):
    schedule = []
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            raise ValueError(f"Invalid input line (expected '<time> <event>'): {line!r}")
        t_s, event_name = parts
        t = parse_time_hhmmssmm(t_s)
        schedule.append((t, event_name))

    schedule.sort(key=lambda x: x[0])

    # Normalize so the simulation clock starts at 0.0 (as required), even if the
    # input uses time-of-day (e.g., 08:00:00:00).
    if schedule:
        t0 = schedule[0][0]
        schedule = [(t - t0, ev) for (t, ev) in schedule]

    return schedule


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Barbershop DES simulation")
    p.add_argument(
        "--simulation_time",
        type=float,
        default=1000000.0,
        help="Maximum simulation time in seconds (default: 1000000.0)",
    )
    return p


def main(argv=None) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(levelname)s: %(message)s")

    args = build_arg_parser().parse_args(argv)

    # Consume ALL stdin lines first to build schedule (required).
    try:
        schedule = read_schedule_from_stdin(sys.stdin)
    except Exception as e:
        logging.error("Failed to parse input schedule: %s", e)
        return 2

    env = simpy.Environment()
    term = TerminationController(env)

    # Create modules (wired after instantiation).
    cuthair = CutHair(env, term)
    checkhair = CheckHair(env, term, cuthair)
    reception = Reception(env, term, checkhair)

    # Wire back-references.
    cuthair.checkhair = checkhair
    checkhair.reception = reception

    term.reception = reception
    term.checkhair = checkhair
    term.cuthair = cuthair

    def arrival_driver() -> simpy.events.Event:
        # Drive all scheduled newcust events.
        for t, event_name in schedule:
            if event_name != "newcust":
                continue
            if t < env.now:
                # Shouldn't happen due to sorting, but guard anyway.
                continue
            yield env.timeout(t - env.now)
            reception.arrive(Customer("newcust"))

        term.arrivals_done = True
        term.maybe_finish()

    env.process(reception.run())
    env.process(checkhair.run())
    env.process(cuthair.run())
    env.process(arrival_driver())

    # Stop when either: simulation time reached, or all work completed.
    timeout_evt = env.timeout(float(args.simulation_time))
    stop_evt = simpy.AnyOf(env, [term.sim_done, timeout_evt])
    env.run(until=stop_evt)

    # Ensure everything buffered is flushed.
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
