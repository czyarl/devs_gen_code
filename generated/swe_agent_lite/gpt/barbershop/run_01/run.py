import argparse
import sys
import json
import logging
from collections import deque

import simpy


def parse_hhmmssff_to_seconds(ts: str) -> float:
    """Parse HH:MM:SS:FF where FF are centiseconds (1/100s) into seconds."""
    parts = ts.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid timestamp: {ts}")
    hh, mm, ss, ff = (int(p) for p in parts)
    return float(hh * 3600 + mm * 60 + ss) + float(ff) / 100.0


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")


class Reception:
    def __init__(self, env: simpy.Environment, checkhair: "CheckHair"):
        self.env = env
        self.checkhair = checkhair
        self.queue = deque()
        self.capacity = 8
        self.processing = False
        self.total_customers_num = 0

    def _state_total(self):
        emit(
            {
                "time": float(self.env.now),
                "type": "state",
                "model": "reception",
                "field": "total customers num",
                "value": self.total_customers_num,
            }
        )

    def _msg_to_checkhair(self, content: str):
        emit(
            {
                "time": float(self.env.now),
                "type": "message",
                "model": "reception",
                "port": "cust",
                "content": content,
            }
        )

    def arrive(self):
        if len(self.queue) >= self.capacity:
            return
        self.queue.append("newcust")
        self.total_customers_num = len(self.queue)
        self._state_total()
        if not self.processing:
            self.processing = True
            self.env.process(self._run())

    def notify_done(self):
        # Notification from checkhair that full service is complete.
        # No explicit output required by spec besides messages/state already emitted elsewhere.
        # But this notification affects reception's ability to handoff waiting customers.
        # We simply trigger the runner by interrupting via event; easiest is to start runner if idle.
        if not self.processing and self.queue:
            self.processing = True
            self.env.process(self._run())

    def _run(self):
        while self.queue:
            # process first in queue for 5 seconds
            yield self.env.timeout(5.0)
            # after 5 seconds, attempt handoff when checkhair available
            while not self.checkhair.is_available():
                # wait a small amount of simulation time to re-check
                yield self.env.timeout(0.1)
            # send customer
            self._msg_to_checkhair("newcust")
            self.checkhair.receive_from_reception("newcust")
            # remove from queue after sent
            self.queue.popleft()
            self.total_customers_num = len(self.queue)
            self._state_total()
        self.processing = False


class CutHair:
    def __init__(self, env: simpy.Environment):
        self.env = env
        self.total_customer_done = 0
        self._done_callback = None

    def set_done_callback(self, cb):
        self._done_callback = cb

    def _state_done(self):
        emit(
            {
                "time": float(self.env.now),
                "type": "state",
                "model": "cuthair",
                "field": "total customer done",
                "value": self.total_customer_done,
            }
        )

    def _msg_out(self, content: str):
        emit(
            {
                "time": float(self.env.now),
                "type": "message",
                "model": "cuthair",
                "port": "out",
                "content": content,
            }
        )

    def receive_from_checkhair(self, content: str):
        self.env.process(self._run_cut(content))

    def _run_cut(self, content: str):
        # process 20 seconds
        yield self.env.timeout(20.0)
        self.total_customer_done += 1
        self._state_done()
        self._msg_out("done")
        if self._done_callback is not None:
            self._done_callback("done")


class CheckHair:
    def __init__(self, env: simpy.Environment, cuthair: CutHair):
        self.env = env
        self.cuthair = cuthair
        self.available = True
        self._inbox = simpy.Store(env)
        self._done_event = None
        self.reception = None
        self.env.process(self._run())

    def set_reception(self, reception: Reception):
        self.reception = reception

    def is_available(self) -> bool:
        return self.available

    def _state_customer(self, value: str):
        emit(
            {
                "time": float(self.env.now),
                "type": "state",
                "model": "checkhair",
                "field": "customer",
                "value": value,
            }
        )

    def _msg_to_cut(self, content: str):
        emit(
            {
                "time": float(self.env.now),
                "type": "message",
                "model": "checkhair",
                "port": "to_cut",
                "content": content,
            }
        )

    def _msg_to_reception(self, content: str):
        emit(
            {
                "time": float(self.env.now),
                "type": "message",
                "model": "checkhair",
                "port": "to_reception",
                "content": content,
            }
        )

    def receive_from_reception(self, content: str):
        self._inbox.put(content)

    def receive_done_from_cuthair(self, content: str):
        if self._done_event is not None and not self._done_event.triggered:
            self._done_event.succeed(content)

    def _run(self):
        while True:
            content = yield self._inbox.get()
            self.available = False
            self._state_customer("newcust")
            # consult 7 seconds
            yield self.env.timeout(7.0)
            # forward to cut
            self._msg_to_cut("newcust")
            self._done_event = self.env.event()
            self.cuthair.receive_from_checkhair("newcust")
            # wait for done
            done_content = yield self._done_event
            # completion
            self._state_customer("done")
            self._msg_to_reception("done")
            if self.reception is not None:
                self.reception.notify_done()
            self.available = True


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.INFO)

    # Read all stdin lines first to build schedule
    schedule = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            ts, ev = line.split()
        except ValueError:
            continue
        if ev != "newcust":
            continue
        t = parse_hhmmssff_to_seconds(ts)
        schedule.append(t)
    schedule.sort()

    env = simpy.Environment()
    cuthair = CutHair(env)
    checkhair = CheckHair(env, cuthair)
    reception = Reception(env, checkhair)
    checkhair.set_reception(reception)
    cuthair.set_done_callback(checkhair.receive_done_from_cuthair)

    def arrivals_proc():
        for t in schedule:
            if t > args.simulation_time:
                break
            yield env.timeout(max(0.0, t - env.now))
            reception.arrive()

    env.process(arrivals_proc())

    env.run(until=args.simulation_time)


if __name__ == "__main__":
    main()
