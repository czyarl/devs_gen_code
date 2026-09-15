import argparse
import json
import logging
import sys
from collections import deque

import simpy


def _parse_time_to_seconds(token: str) -> float:
    # Format: HH:MM:SS:mm where the last field is fractional seconds.
    parts = token.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid time token (expected HH:MM:SS:mm): {token!r}")

    hh, mm, ss, frac = parts
    hours = int(hh)
    minutes = int(mm)
    seconds = int(ss)
    frac_i = int(frac)
    denom = 10 ** len(frac) if frac else 1
    return hours * 3600 + minutes * 60 + seconds + (frac_i / denom)


class JsonlEmitter:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def state(self, model: str, field: str, value):
        obj = {
            "time": float(self.env.now),
            "type": "state",
            "model": model,
            "field": field,
            "value": value,
        }
        print(json.dumps(obj), file=sys.stdout, flush=True)

    def message(self, model: str, port: str, content: str):
        obj = {
            "time": float(self.env.now),
            "type": "message",
            "model": model,
            "port": port,
            "content": content,
        }
        print(json.dumps(obj), file=sys.stdout, flush=True)


class Reception:
    QUEUE_CAPACITY = 8
    CHECKIN_TIME = 5.0

    def __init__(self, env: simpy.Environment, emitter: JsonlEmitter):
        self.env = env
        self.emitter = emitter
        self.queue = deque()
        self._new_customer_event = env.event()
        self.done_in = simpy.Store(env)
        self.checkhair = None

    def connect_checkhair(self, checkhair: "CheckHair"):
        self.checkhair = checkhair

    def arrive(self):
        if len(self.queue) >= self.QUEUE_CAPACITY:
            return
        self.queue.append(1)
        self.emitter.state("reception", "total customers num", len(self.queue))
        if not self._new_customer_event.triggered:
            self._new_customer_event.succeed()

    def _wait_for_customer(self):
        if self.queue:
            return self.env.timeout(0)
        self._new_customer_event = self.env.event()
        return self._new_customer_event

    def run(self):
        while True:
            yield self._wait_for_customer()

            # Process the first customer in the queue for exactly 5 seconds.
            yield self.env.timeout(self.CHECKIN_TIME)

            # After check-in, wait until checkhair is available, then handoff.
            yield self.checkhair.available_event

            self.queue.popleft()
            self.emitter.state("reception", "total customers num", len(self.queue))
            self.emitter.message("reception", "cust", "newcust")
            yield self.checkhair.in_cust.put("newcust")


class CheckHair:
    CONSULT_TIME = 7.0

    def __init__(self, env: simpy.Environment, emitter: JsonlEmitter):
        self.env = env
        self.emitter = emitter
        self.in_cust = simpy.Store(env)
        self.in_done = simpy.Store(env)
        self.cuthair = None
        self.reception = None
        self.available_event = env.event()
        self.available_event.succeed()  # Initially available

    def connect(self, cuthair: "CutHair", reception: Reception):
        self.cuthair = cuthair
        self.reception = reception

    def _set_busy(self):
        # Reset availability for future waiters.
        self.available_event = self.env.event()

    def _set_available(self):
        if not self.available_event.triggered:
            self.available_event.succeed()

    def run(self):
        while True:
            self._set_available()
            cust = yield self.in_cust.get()
            self._set_busy()

            self.emitter.state("checkhair", "customer", cust)
            yield self.env.timeout(self.CONSULT_TIME)

            self.emitter.message("checkhair", "to_cut", "newcust")
            yield self.cuthair.in_cust.put(cust)

            # Wait until cutting is done before allowing next customer.
            _ = yield self.in_done.get()
            self.emitter.state("checkhair", "customer", "done")

            self.emitter.message("checkhair", "to_reception", "done")
            yield self.reception.done_in.put("done")


class CutHair:
    CUT_TIME = 20.0

    def __init__(self, env: simpy.Environment, emitter: JsonlEmitter):
        self.env = env
        self.emitter = emitter
        self.in_cust = simpy.Store(env)
        self.checkhair = None
        self.total_done = 0

    def connect_checkhair(self, checkhair: CheckHair):
        self.checkhair = checkhair

    def run(self):
        while True:
            _ = yield self.in_cust.get()
            yield self.env.timeout(self.CUT_TIME)

            self.total_done += 1
            self.emitter.state("cuthair", "total customer done", self.total_done)
            self.emitter.message("cuthair", "out", "done")
            yield self.checkhair.in_done.put("done")


def _read_schedule_from_stdin() -> list[tuple[float, str]]:
    lines = sys.stdin.read().splitlines()
    schedule = []
    for idx, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        try:
            t_token, event_name = line.split(None, 1)
        except ValueError as e:
            raise ValueError(f"Invalid schedule line: {raw!r}") from e
        if event_name.strip() != "newcust":
            raise ValueError(f"Unsupported event name: {event_name!r}")
        t = _parse_time_to_seconds(t_token)
        schedule.append((t, "newcust"))

    if not schedule:
        return []

    t0 = min(t for t, _ in schedule)
    normalized = [(t - t0, ev) for t, ev in schedule]
    normalized.sort(key=lambda x: x[0])
    return normalized


def _install_arrivals(env: simpy.Environment, reception: Reception, schedule: list[tuple[float, str]]):
    def arrival_process():
        for t, _ in schedule:
            if t < env.now:
                continue
            yield env.timeout(t - env.now)
            reception.arrive()

    env.process(arrival_process())


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(levelname)s:%(message)s")

    schedule = _read_schedule_from_stdin()

    env = simpy.Environment()
    emitter = JsonlEmitter(env)

    reception = Reception(env, emitter)
    checkhair = CheckHair(env, emitter)
    cuthair = CutHair(env, emitter)

    reception.connect_checkhair(checkhair)
    checkhair.connect(cuthair, reception)
    cuthair.connect_checkhair(checkhair)

    env.process(reception.run())
    env.process(checkhair.run())
    env.process(cuthair.run())

    _install_arrivals(env, reception, schedule)

    env.run(until=float(args.simulation_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
