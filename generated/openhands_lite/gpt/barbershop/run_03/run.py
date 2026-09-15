#!/usr/bin/env python3
import argparse
import json
import logging
import sys
from collections import deque

import simpy


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _parse_time_to_seconds(ts: str) -> float:
    parts = ts.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid time format (expected HH:MM:SS:mm): {ts!r}")
    hh_s, mm_s, ss_s, frac_s = parts
    hh = int(hh_s)
    mm = int(mm_s)
    ss = int(ss_s)
    frac_int = int(frac_s)
    denom = 10 ** len(frac_s) if len(frac_s) else 1
    frac = frac_int / denom
    return hh * 3600.0 + mm * 60.0 + ss + frac


class CheckHair:
    def __init__(self, env: simpy.Environment, cuthair: "CutHair"):
        self.env = env
        self.cuthair = cuthair
        self.inbox: simpy.Store = simpy.Store(env)

        self.available = True
        self._available_event: simpy.Event = env.event()
        self._available_event.succeed()

        self._proc = env.process(self._run())

    @property
    def available_event(self) -> simpy.Event:
        return self._available_event

    def reserve_for_incoming(self) -> None:
        if not self.available:
            raise RuntimeError("checkhair is not available")
        self.available = False
        self._available_event = self.env.event()

    def mark_available(self) -> None:
        if self.available:
            return
        self.available = True
        if not self._available_event.triggered:
            self._available_event.succeed()

    def accept(self, customer) -> simpy.Event:
        return self.inbox.put(customer)

    def _run(self):
        while True:
            customer = yield self.inbox.get()
            _emit(
                {
                    "time": float(self.env.now),
                    "type": "state",
                    "model": "checkhair",
                    "field": "customer",
                    "value": "newcust",
                }
            )

            yield self.env.timeout(7.0)

            _emit(
                {
                    "time": float(self.env.now),
                    "type": "message",
                    "model": "checkhair",
                    "port": "to_cut",
                    "content": "newcust",
                }
            )

            done_event = self.env.event()
            yield self.cuthair.accept((customer, done_event))
            yield done_event

            _emit(
                {
                    "time": float(self.env.now),
                    "type": "state",
                    "model": "checkhair",
                    "field": "customer",
                    "value": "done",
                }
            )
            _emit(
                {
                    "time": float(self.env.now),
                    "type": "message",
                    "model": "checkhair",
                    "port": "to_reception",
                    "content": "done",
                }
            )
            self.mark_available()


class CutHair:
    def __init__(self, env: simpy.Environment):
        self.env = env
        self.inbox: simpy.Store = simpy.Store(env)
        self.total_done = 0
        self._proc = env.process(self._run())

    def accept(self, item) -> simpy.Event:
        return self.inbox.put(item)

    def _run(self):
        while True:
            _customer, done_event = yield self.inbox.get()
            yield self.env.timeout(20.0)
            self.total_done += 1
            _emit(
                {
                    "time": float(self.env.now),
                    "type": "state",
                    "model": "cuthair",
                    "field": "total customer done",
                    "value": self.total_done,
                }
            )
            _emit(
                {
                    "time": float(self.env.now),
                    "type": "message",
                    "model": "cuthair",
                    "port": "out",
                    "content": "done",
                }
            )
            if not done_event.triggered:
                done_event.succeed()


class Reception:
    def __init__(self, env: simpy.Environment, checkhair: CheckHair):
        self.env = env
        self.checkhair = checkhair

        self.queue = deque()
        self.capacity = 8
        self._queue_nonempty_event: simpy.Event = env.event()

        self._proc = env.process(self._run())

    def _set_queue_nonempty(self) -> None:
        if not self._queue_nonempty_event.triggered:
            self._queue_nonempty_event.succeed()

    def arrive(self) -> None:
        if len(self.queue) >= self.capacity:
            return
        self.queue.append(object())
        _emit(
            {
                "time": float(self.env.now),
                "type": "state",
                "model": "reception",
                "field": "total customers num",
                "value": len(self.queue),
            }
        )
        self._set_queue_nonempty()

    def _run(self):
        while True:
            while not self.queue:
                self._queue_nonempty_event = self.env.event()
                yield self._queue_nonempty_event

            yield self.env.timeout(5.0)

            while not self.checkhair.available:
                yield self.checkhair.available_event

            self.checkhair.reserve_for_incoming()

            self.queue.popleft()
            _emit(
                {
                    "time": float(self.env.now),
                    "type": "state",
                    "model": "reception",
                    "field": "total customers num",
                    "value": len(self.queue),
                }
            )
            _emit(
                {
                    "time": float(self.env.now),
                    "type": "message",
                    "model": "reception",
                    "port": "cust",
                    "content": "newcust",
                }
            )
            yield self.checkhair.accept("newcust")


def _read_schedule_from_stdin(logger: logging.Logger):
    events = []
    for line_no, raw in enumerate(sys.stdin, start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            ts, name = line.split(None, 1)
        except ValueError:
            logger.warning("Ignoring malformed line %d: %r", line_no, line)
            continue
        if name.strip() != "newcust":
            logger.warning("Ignoring unknown event %r on line %d", name.strip(), line_no)
            continue
        try:
            t = _parse_time_to_seconds(ts)
        except Exception:
            logger.warning("Ignoring bad timestamp %r on line %d", ts, line_no)
            continue
        events.append(t)

    if not events:
        return []

    t0 = min(events)
    normalized = [t - t0 for t in events]
    normalized.sort()
    return normalized


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=1000000.0,
        help="Total simulation time in seconds",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")
    logger = logging.getLogger("barbershop")

    schedule = _read_schedule_from_stdin(logger)
    logger.info("Loaded %d scheduled arrivals", len(schedule))

    env = simpy.Environment(initial_time=0.0)
    cuthair = CutHair(env)
    checkhair = CheckHair(env, cuthair)
    reception = Reception(env, checkhair)

    def arrivals_proc():
        for t in schedule:
            dt = t - env.now
            if dt > 0:
                yield env.timeout(dt)
            reception.arrive()

    env.process(arrivals_proc())

    try:
        stop_event = env.timeout(float(args.simulation_time))
        env.run(until=stop_event)
    except Exception as e:
        logger.error("Simulation failed: %s", e)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
