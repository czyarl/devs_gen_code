#!/usr/bin/env python3
import argparse
import collections
import json
import logging
import sys
from dataclasses import dataclass

import simpy


def parse_hhmmsscc(token: str) -> float:
    hh_s, mm_s, ss_s, cc_s = token.split(":")
    hh = int(hh_s)
    mm = int(mm_s)
    ss = int(ss_s)
    cc = int(cc_s)
    return hh * 3600.0 + mm * 60.0 + ss + (cc / 100.0)


@dataclass(frozen=True)
class Customer:
    kind: str = "newcust"


class Emitter:
    def __init__(self, out_stream):
        self._out = out_stream

    def emit(self, obj: dict) -> None:
        self._out.write(json.dumps(obj) + "\n")


class CutHair:
    def __init__(self, env: simpy.Environment, emit: Emitter):
        self.env = env
        self.emit = emit
        self.inbox: simpy.Store = simpy.Store(env)
        self.total_done = 0
        self._proc = env.process(self._run())

    def _state_total_done(self) -> None:
        self.emit.emit(
            {
                "time": float(self.env.now),
                "type": "state",
                "model": "cuthair",
                "field": "total customer done",
                "value": self.total_done,
            }
        )

    def _msg_out_done(self) -> None:
        self.emit.emit(
            {
                "time": float(self.env.now),
                "type": "message",
                "model": "cuthair",
                "port": "out",
                "content": "done",
            }
        )

    def _run(self):
        while True:
            customer, done_event = yield self.inbox.get()
            _ = customer
            yield self.env.timeout(20.0)
            self.total_done += 1
            self._state_total_done()
            self._msg_out_done()
            if not done_event.triggered:
                done_event.succeed()


class CheckHair:
    def __init__(self, env: simpy.Environment, emit: Emitter, cutter: CutHair):
        self.env = env
        self.emit = emit
        self.cutter = cutter
        self.inbox: simpy.Store = simpy.Store(env)
        self.ready: simpy.Event = simpy.Event(env)
        self.ready.succeed()
        self._proc = env.process(self._run())

    def _state_customer(self, value: str) -> None:
        self.emit.emit(
            {
                "time": float(self.env.now),
                "type": "state",
                "model": "checkhair",
                "field": "customer",
                "value": value,
            }
        )

    def _msg_to_cut(self) -> None:
        self.emit.emit(
            {
                "time": float(self.env.now),
                "type": "message",
                "model": "checkhair",
                "port": "to_cut",
                "content": "newcust",
            }
        )

    def _msg_to_reception_done(self) -> None:
        self.emit.emit(
            {
                "time": float(self.env.now),
                "type": "message",
                "model": "checkhair",
                "port": "to_reception",
                "content": "done",
            }
        )

    def _run(self):
        while True:
            customer = yield self.inbox.get()
            self.ready = simpy.Event(self.env)
            _ = customer
            self._state_customer("newcust")
            yield self.env.timeout(7.0)

            done_event = simpy.Event(self.env)
            self._msg_to_cut()
            yield self.cutter.inbox.put((customer, done_event))
            yield done_event

            self._state_customer("done")
            self._msg_to_reception_done()

            if not self.ready.triggered:
                self.ready.succeed()


class Reception:
    def __init__(self, env: simpy.Environment, emit: Emitter, checker: CheckHair):
        self.env = env
        self.emit = emit
        self.checker = checker
        self.capacity = 8
        self.queue: collections.deque[Customer] = collections.deque()
        self._wake: simpy.Event = simpy.Event(env)
        self._proc = env.process(self._run())

    def _state_total_customers(self) -> None:
        self.emit.emit(
            {
                "time": float(self.env.now),
                "type": "state",
                "model": "reception",
                "field": "total customers num",
                "value": len(self.queue),
            }
        )

    def _msg_cust(self) -> None:
        self.emit.emit(
            {
                "time": float(self.env.now),
                "type": "message",
                "model": "reception",
                "port": "cust",
                "content": "newcust",
            }
        )

    def arrive(self, customer: Customer) -> None:
        if len(self.queue) >= self.capacity:
            return
        self.queue.append(customer)
        self._state_total_customers()
        if not self._wake.triggered:
            self._wake.succeed()

    def _run(self):
        while True:
            if not self.queue:
                self._wake = simpy.Event(self.env)
                yield self._wake

            yield self.env.timeout(5.0)
            yield self.checker.ready

            customer = self.queue[0]
            self._msg_cust()
            yield self.checker.inbox.put(customer)
            self.queue.popleft()
            self._state_total_customers()


def read_schedule(stdin_text: str, logger: logging.Logger) -> list[float]:
    times: list[float] = []
    for raw in stdin_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 2:
            logger.warning("Ignoring malformed line: %r", raw)
            continue
        ts, name = parts
        if name != "newcust":
            logger.warning("Ignoring unknown event %r in line: %r", name, raw)
            continue
        try:
            times.append(parse_hhmmsscc(ts))
        except Exception:
            logger.warning("Ignoring bad timestamp %r in line: %r", ts, raw)

    # The simulation clock starts at 0.0, and HH:MM:SS:cc is interpreted
    # as an absolute offset from 00:00:00:00.
    return sorted(times)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--simulation_time",
        type=float,
        default=1000000.0,
        help="Total simulation time in seconds.",
    )
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s:%(name)s:%(message)s",
        stream=sys.stderr,
    )
    logger = logging.getLogger("barbershop")

    stdin_text = sys.stdin.read()
    schedule = read_schedule(stdin_text, logger)

    env = simpy.Environment()
    emit = Emitter(sys.stdout)

    cutter = CutHair(env, emit)
    checker = CheckHair(env, emit, cutter)
    reception = Reception(env, emit, checker)

    def arrival_at(t: float):
        yield env.timeout(t)
        reception.arrive(Customer("newcust"))

    for t in schedule:
        env.process(arrival_at(float(t)))

    env.run(until=float(args.simulation_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
