#!/usr/bin/env python3
"""Barbershop discrete-event simulation.

Entry point: python run.py

Reads a schedule from stdin (one event per line), builds the initial event list
*before* starting the SimPy environment, then runs a DES simulation.

STDOUT: JSONL records only (state changes + inter-module messages)
STDERR: logging / diagnostics
"""

import argparse
import json
import logging
import sys
from collections import deque

import simpy


def parse_hhmmssff_to_seconds(s: str) -> float:
    """Parse HH:MM:SS:mm into seconds.

    The last field (mm) is treated as centiseconds (1/100 second).
    """
    parts = s.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid time format (expected HH:MM:SS:mm): {s!r}")
    hh, mm, ss, ff = (int(p) for p in parts)
    return hh * 3600.0 + mm * 60.0 + ss + ff / 100.0


class Emitter:
    """Emit JSONL records to stdout only.

    When stdout is closed early (e.g., piped through `head`), further writes would
    raise BrokenPipeError. We disable further output in that case to allow a clean
    exit.
    """

    def __init__(self, out_stream):
        self._out = out_stream
        self._disabled = False

    def emit(self, obj: dict) -> None:
        if self._disabled:
            return
        try:
            self._out.write(json.dumps(obj, ensure_ascii=False) + "\n")
        except BrokenPipeError:
            self._disabled = True


class CutHair:
    """Hair cutting phase (cuthair)."""

    def __init__(self, env: simpy.Environment, emit: Emitter):
        self.env = env
        self.emit = emit

        self.inbox = simpy.Store(env)  # receives "newcust" tokens
        self.done_outbox = None  # wired to checkhair.done_inbox

        self.total_done = 0

    def set_done_outbox(self, outbox: simpy.Store) -> None:
        self.done_outbox = outbox

    def run(self):
        while True:
            _cust = yield self.inbox.get()
            # Process cutting
            yield self.env.timeout(20.0)

            # Update cumulative counter
            self.total_done += 1
            self.emit.emit(
                {
                    "time": float(self.env.now),
                    "type": "state",
                    "model": "cuthair",
                    "field": "total customer done",
                    "value": self.total_done,
                }
            )

            # Signal done back to checkhair
            self.emit.emit(
                {
                    "time": float(self.env.now),
                    "type": "message",
                    "model": "cuthair",
                    "port": "out",
                    "content": "done",
                }
            )
            if self.done_outbox is None:
                raise RuntimeError("cuthair.done_outbox not wired")
            yield self.done_outbox.put("done")


class CheckHair:
    """Hair inspection phase (checkhair)."""

    def __init__(self, env: simpy.Environment, emit: Emitter):
        self.env = env
        self.emit = emit

        self.inbox = simpy.Store(env)  # receives "newcust" tokens
        self.done_inbox = simpy.Store(env)  # receives "done" from cuthair

        self.to_cut_outbox = None  # wired to cuthair.inbox
        self.to_reception_outbox = None  # wired to reception.done_inbox

        self._available = True
        self._available_event = env.event()
        self._available_event.succeed()  # initially available

    @property
    def available(self) -> bool:
        return self._available

    @property
    def available_event(self) -> simpy.Event:
        return self._available_event

    def set_to_cut_outbox(self, outbox: simpy.Store) -> None:
        self.to_cut_outbox = outbox

    def set_to_reception_outbox(self, outbox: simpy.Store) -> None:
        self.to_reception_outbox = outbox

    def run(self):
        while True:
            _cust = yield self.inbox.get()

            # Become busy (not available for new customers until full cycle completes)
            self._available = False
            self._available_event = self.env.event()  # reset; will succeed when available again

            # Start inspection
            self.emit.emit(
                {
                    "time": float(self.env.now),
                    "type": "state",
                    "model": "checkhair",
                    "field": "customer",
                    "value": "newcust",
                }
            )
            yield self.env.timeout(7.0)

            # Forward to cutting
            self.emit.emit(
                {
                    "time": float(self.env.now),
                    "type": "message",
                    "model": "checkhair",
                    "port": "to_cut",
                    "content": "newcust",
                }
            )
            if self.to_cut_outbox is None:
                raise RuntimeError("checkhair.to_cut_outbox not wired")
            yield self.to_cut_outbox.put("newcust")

            # Wait for cutter completion signal
            _done = yield self.done_inbox.get()

            # Update inspection state with completion
            self.emit.emit(
                {
                    "time": float(self.env.now),
                    "type": "state",
                    "model": "checkhair",
                    "field": "customer",
                    "value": "done",
                }
            )

            # Notify reception that full service is complete
            self.emit.emit(
                {
                    "time": float(self.env.now),
                    "type": "message",
                    "model": "checkhair",
                    "port": "to_reception",
                    "content": "done",
                }
            )
            if self.to_reception_outbox is None:
                raise RuntimeError("checkhair.to_reception_outbox not wired")
            yield self.to_reception_outbox.put("done")

            # Become available again
            self._available = True
            self._available_event.succeed()


class Reception:
    """Reception desk module (reception)."""

    def __init__(self, env: simpy.Environment, emit: Emitter, checkhair: CheckHair):
        self.env = env
        self.emit = emit
        self.checkhair = checkhair

        self.capacity = 8
        self.queue = deque()  # tokens, each is "newcust"

        self._queue_nonempty_event = env.event()

        # Optional inbox for done notifications (consumed to avoid growth)
        self.done_inbox = simpy.Store(env)

    def arrive(self) -> None:
        if len(self.queue) >= self.capacity:
            return
        self.queue.append("newcust")
        self.emit.emit(
            {
                "time": float(self.env.now),
                "type": "state",
                "model": "reception",
                "field": "total customers num",
                "value": len(self.queue),
            }
        )
        if not self._queue_nonempty_event.triggered:
            self._queue_nonempty_event.succeed()

    def run(self):
        while True:
            if not self.queue:
                self._queue_nonempty_event = self.env.event()
                yield self._queue_nonempty_event

            # Process the first-in-queue customer for exactly 5 seconds.
            yield self.env.timeout(5.0)

            # After 5 seconds, hand off only if checkhair is available.
            while not self.checkhair.available:
                yield self.checkhair.available_event

            # Send to checkhair.
            _cust = self.queue.popleft()
            self.emit.emit(
                {
                    "time": float(self.env.now),
                    "type": "state",
                    "model": "reception",
                    "field": "total customers num",
                    "value": len(self.queue),
                }
            )
            self.emit.emit(
                {
                    "time": float(self.env.now),
                    "type": "message",
                    "model": "reception",
                    "port": "cust",
                    "content": "newcust",
                }
            )
            yield self.checkhair.inbox.put(_cust)

    def consume_done_notifications(self):
        while True:
            _ = yield self.done_inbox.get()
            # No required state variable in reception for completion; just consume.
            # Logging of the message is performed by the sender (checkhair).


def build_schedule_from_stdin(log: logging.Logger):
    lines = sys.stdin.read().splitlines()
    schedule = []

    for idx, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            ts_str, ev_name = line.split(maxsplit=1)
        except ValueError:
            log.warning("Skipping malformed line %d: %r", idx, raw)
            continue
        if ev_name.strip() != "newcust":
            log.warning("Skipping unknown event %r on line %d", ev_name, idx)
            continue
        try:
            t = parse_hhmmssff_to_seconds(ts_str)
        except Exception as e:
            log.warning("Skipping line %d due to time parse error: %s", idx, e)
            continue
        schedule.append((t, "newcust"))

    schedule.sort(key=lambda x: x[0])

    # Normalize to clock start at 0.0
    if schedule:
        t0 = schedule[0][0]
        schedule = [(t - t0, ev) for (t, ev) in schedule]

    return schedule


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Barbershop DES simulation")
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=1000000.0,
        help="Total simulation time in seconds (default: 1000000.0)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="[%(levelname)s] %(message)s",
    )
    log = logging.getLogger("barbershop")

    # 1) Consume ALL stdin and build schedule BEFORE starting simulation.
    schedule = build_schedule_from_stdin(log)
    log.info("Loaded %d scheduled arrivals", len(schedule))

    # 2) Create DES environment and wire modules.
    env = simpy.Environment(initial_time=0.0)
    emitter = Emitter(sys.stdout)

    checkhair = CheckHair(env, emitter)
    cuthair = CutHair(env, emitter)
    reception = Reception(env, emitter, checkhair)

    # Wiring: checkhair -> cuthair, cuthair -> checkhair, checkhair -> reception
    checkhair.set_to_cut_outbox(cuthair.inbox)
    cuthair.set_done_outbox(checkhair.done_inbox)
    checkhair.set_to_reception_outbox(reception.done_inbox)

    # 3) Start module processes.
    env.process(reception.run())
    env.process(reception.consume_done_notifications())
    env.process(checkhair.run())
    env.process(cuthair.run())

    # 4) Create a single arrival driver process based on the pre-built schedule.
    # This avoids creating one SimPy process per input line.
    def arrival_driver():
        last_t = 0.0
        for t, _ev in schedule:
            dt = t - last_t
            if dt > 0:
                yield env.timeout(dt)
            reception.arrive()
            last_t = t

    env.process(arrival_driver())

    # 5) Run simulation.
    # SimPy will stop early if no events remain even if `until` is large.
    env.run(until=float(args.simulation_time))

    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
