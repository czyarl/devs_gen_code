import argparse
import sys
import json
import logging
from collections import deque

import simpy


def parse_hhmmssff_to_seconds(ts: str) -> float:
    """Parse HH:MM:SS:mm into absolute seconds.

    The last field (mm) is treated as centiseconds (1/100s).
    """
    parts = ts.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {ts}")
    hh, mm, ss, ff = (int(p) for p in parts)
    return hh * 3600 + mm * 60 + ss + ff / 100.0


class JsonlEmitter:
    def __init__(self, out_stream):
        self.out = out_stream

    def emit(self, obj):
        self.out.write(json.dumps(obj) + "\n")
        self.out.flush()


class CheckHair:
    def __init__(self, env: simpy.Environment, emitter: JsonlEmitter):
        self.env = env
        self.emitter = emitter
        self.inbox = simpy.Store(env)  # receives customers from reception
        self.to_cut = None  # set later
        self.to_reception = None  # callback set later
        self.done_signal = simpy.Store(env)  # receives done from cutter
        self.available = True
        self.proc = env.process(self.run())

    def _state_customer(self, value: str):
        self.emitter.emit(
            {
                "time": float(self.env.now),
                "type": "state",
                "model": "checkhair",
                "field": "customer",
                "value": value,
            }
        )

    def _msg(self, port: str, content: str):
        self.emitter.emit(
            {
                "time": float(self.env.now),
                "type": "message",
                "model": "checkhair",
                "port": port,
                "content": content,
            }
        )

    def is_available(self) -> bool:
        return self.available

    def put_customer(self, content: str):
        return self.inbox.put(content)

    def put_done(self, content: str):
        return self.done_signal.put(content)

    def run(self):
        while True:
            cust = yield self.inbox.get()
            self.available = False
            # processing start
            self._state_customer("newcust")
            yield self.env.timeout(7.0)
            # forward to cutter
            self._msg("to_cut", "newcust")
            yield self.to_cut.put_customer("newcust")
            # wait for done from cutter
            done = yield self.done_signal.get()
            # completion state
            self._state_customer(done)
            # notify reception full service complete
            self._msg("to_reception", done)
            yield self.to_reception.put_done(done)
            self.available = True


class CutHair:
    def __init__(self, env: simpy.Environment, emitter: JsonlEmitter):
        self.env = env
        self.emitter = emitter
        self.inbox = simpy.Store(env)  # receives from checkhair
        self.to_checkhair = None  # set later
        self.total_done = 0
        self.proc = env.process(self.run())

    def _state_total_done(self):
        self.emitter.emit(
            {
                "time": float(self.env.now),
                "type": "state",
                "model": "cuthair",
                "field": "total customer done",
                "value": self.total_done,
            }
        )

    def _msg(self, port: str, content: str):
        self.emitter.emit(
            {
                "time": float(self.env.now),
                "type": "message",
                "model": "cuthair",
                "port": port,
                "content": content,
            }
        )

    def put_customer(self, content: str):
        return self.inbox.put(content)

    def run(self):
        while True:
            _cust = yield self.inbox.get()
            yield self.env.timeout(20.0)
            self.total_done += 1
            self._state_total_done()
            self._msg("out", "done")
            yield self.to_checkhair.put_done("done")


class Reception:
    def __init__(self, env: simpy.Environment, emitter: JsonlEmitter):
        self.env = env
        self.emitter = emitter
        self.queue = deque()
        self.capacity = 8
        self.checkhair = None  # set later
        self.done_inbox = simpy.Store(env)  # receives done notifications
        self.proc = env.process(self.run())

    def _state_total_customers(self):
        self.emitter.emit(
            {
                "time": float(self.env.now),
                "type": "state",
                "model": "reception",
                "field": "total customers num",
                "value": len(self.queue),
            }
        )

    def _msg(self, port: str, content: str):
        self.emitter.emit(
            {
                "time": float(self.env.now),
                "type": "message",
                "model": "reception",
                "port": port,
                "content": content,
            }
        )

    def arrive(self, content: str):
        if len(self.queue) < self.capacity:
            self.queue.append(content)
            self._state_total_customers()
        # else ignore

    def put_done(self, content: str):
        return self.done_inbox.put(content)

    def run(self):
        while True:
            if not self.queue:
                # wait until either a new arrival triggers (polled) or done arrives
                # We don't have an arrival event store; just yield a small timeout.
                yield self.env.timeout(0.01)
                continue

            # process first in queue for 5 seconds (still in queue)
            yield self.env.timeout(5.0)

            # after 5 seconds, wait until checkhair available
            while not self.checkhair.is_available():
                yield self.env.timeout(0.01)

            # handoff
            self.queue.popleft()
            self._state_total_customers()
            self._msg("cust", "newcust")
            yield self.checkhair.put_customer("newcust")


def build_schedule_from_stdin():
    schedule = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            ts, ev = line.split()
        except ValueError:
            raise ValueError(f"Invalid input line: {line}")
        if ev != "newcust":
            continue
        t = parse_hhmmssff_to_seconds(ts)
        schedule.append((t, ev))
    schedule.sort(key=lambda x: x[0])
    return schedule


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)

    schedule = build_schedule_from_stdin()

    env = simpy.Environment()
    emitter = JsonlEmitter(sys.stdout)

    reception = Reception(env, emitter)
    checkhair = CheckHair(env, emitter)
    cuthair = CutHair(env, emitter)

    # wire modules
    reception.checkhair = checkhair
    checkhair.to_cut = cuthair
    checkhair.to_reception = reception
    cuthair.to_checkhair = checkhair

    def source_process():
        for t, ev in schedule:
            if t > args.simulation_time:
                break
            yield env.timeout(max(0.0, t - env.now))
            reception.arrive(ev)

    env.process(source_process())

    env.run(until=args.simulation_time)


if __name__ == "__main__":
    main()
