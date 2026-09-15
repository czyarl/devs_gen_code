import argparse
import sys
import json
import logging
from collections import deque

import simpy


def parse_hhmmssff_to_seconds(ts: str) -> float:
    """Parse HH:MM:SS:mm into absolute seconds.

    The last field (mm) is treated as hundredths of a second.
    """
    parts = ts.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid timestamp: {ts}")
    hh, mm, ss, ff = (int(p) for p in parts)
    return hh * 3600 + mm * 60 + ss + ff / 100.0


class JsonlEmitter:
    def __init__(self, out_stream):
        self.out = out_stream

    def emit(self, obj: dict):
        self.out.write(json.dumps(obj) + "\n")
        self.out.flush()


class Reception:
    """Reception desk with capacity-limited waiting area and 5s check-in."""

    def __init__(self, env: simpy.Environment, emitter: JsonlEmitter, checkhair: "CheckHair"):
        self.env = env
        self.emitter = emitter
        self.checkhair = checkhair

        self.queue = deque()
        self.capacity = 8

        # Event used to wake the processing loop when new customers arrive
        self._new_customer_event = env.event()

        # Event used to wake the processing loop when checkhair becomes available
        self._checkhair_available_event = env.event()

        env.process(self._run())

    def _emit_state_total(self):
        self.emitter.emit(
            {
                "time": float(self.env.now),
                "type": "state",
                "model": "reception",
                "field": "total customers num",
                "value": len(self.queue),
            }
        )

    def _emit_message(self, port: str, content: str):
        self.emitter.emit(
            {
                "time": float(self.env.now),
                "type": "message",
                "model": "reception",
                "port": port,
                "content": content,
            }
        )

    def arrive(self, content: str = "newcust"):
        # Arrival: accept if queue < 8 else ignore
        if len(self.queue) >= self.capacity:
            return
        self.queue.append(content)
        self._emit_state_total()
        if not self._new_customer_event.triggered:
            self._new_customer_event.succeed()
        self._new_customer_event = self.env.event()

    def notify_service_complete(self):
        # Called by checkhair when full service is complete.
        if not self._checkhair_available_event.triggered:
            self._checkhair_available_event.succeed()
        self._checkhair_available_event = self.env.event()

    def _checkhair_available(self) -> bool:
        return self.checkhair.is_available

    def _run(self):
        while True:
            # Wait until there is at least one customer
            if not self.queue:
                yield self._new_customer_event
                continue

            # Process first in queue for exactly 5 seconds (still in queue)
            yield self.env.timeout(5.0)

            # After 5 seconds, attempt handoff when checkhair is available
            while self.queue and not self._checkhair_available():
                # Wait until checkhair signals availability
                yield self._checkhair_available_event

            if not self.queue:
                continue

            cust = self.queue.popleft()
            self._emit_state_total()
            self._emit_message("cust", "newcust")
            self.checkhair.receive_from_reception(cust)


class CheckHair:
    """Hair inspection phase: 7s consult, forwards to cutter, waits for done."""

    def __init__(self, env: simpy.Environment, emitter: JsonlEmitter):
        self.env = env
        self.emitter = emitter

        self.is_available = True

        self._inbox = simpy.Store(env)
        self._done_from_cutter = simpy.Store(env)

        self.cuthair = None  # set later
        self.reception = None  # set later

        env.process(self._run())

    def _emit_state_customer(self, value: str):
        self.emitter.emit(
            {
                "time": float(self.env.now),
                "type": "state",
                "model": "checkhair",
                "field": "customer",
                "value": value,
            }
        )

    def _emit_message(self, port: str, content: str):
        self.emitter.emit(
            {
                "time": float(self.env.now),
                "type": "message",
                "model": "checkhair",
                "port": port,
                "content": content,
            }
        )

    def receive_from_reception(self, cust: str):
        self._inbox.put(cust)

    def receive_done_from_cutter(self, msg: str):
        self._done_from_cutter.put(msg)

    def _run(self):
        while True:
            cust = yield self._inbox.get()
            self.is_available = False

            # Start processing
            self._emit_state_customer("newcust")
            yield self.env.timeout(7.0)

            # Forward to cutting
            self._emit_message("to_cut", "newcust")
            self.cuthair.receive_from_checkhair(cust)

            # Wait for done from cutter
            _ = yield self._done_from_cutter.get()

            # Completion: notify reception and become available
            self._emit_state_customer("done")
            self._emit_message("to_reception", "done")
            self.reception.notify_service_complete()

            self.is_available = True


class CutHair:
    """Hair cutting phase: 20s, then signals done back to checkhair."""

    def __init__(self, env: simpy.Environment, emitter: JsonlEmitter):
        self.env = env
        self.emitter = emitter

        self._inbox = simpy.Store(env)
        self.checkhair = None  # set later

        self.total_done = 0

        env.process(self._run())

    def _emit_state_total_done(self):
        self.emitter.emit(
            {
                "time": float(self.env.now),
                "type": "state",
                "model": "cuthair",
                "field": "total customer done",
                "value": self.total_done,
            }
        )

    def _emit_message(self, port: str, content: str):
        self.emitter.emit(
            {
                "time": float(self.env.now),
                "type": "message",
                "model": "cuthair",
                "port": port,
                "content": content,
            }
        )

    def receive_from_checkhair(self, cust: str):
        self._inbox.put(cust)

    def _run(self):
        while True:
            _cust = yield self._inbox.get()
            yield self.env.timeout(20.0)
            self.total_done += 1
            self._emit_state_total_done()
            self._emit_message("out", "done")
            self.checkhair.receive_done_from_cutter("done")


def build_initial_schedule(stdin) -> list[tuple[float, str]]:
    schedule = []
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            ts, ev = line.split(maxsplit=1)
        except ValueError:
            raise ValueError(f"Invalid input line: {line}")
        if ev.strip() != "newcust":
            continue
        t = parse_hhmmssff_to_seconds(ts)
        schedule.append((t, "newcust"))
    schedule.sort(key=lambda x: x[0])
    return schedule


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")

    schedule = build_initial_schedule(sys.stdin)

    env = simpy.Environment(initial_time=0.0)
    emitter = JsonlEmitter(sys.stdout)

    checkhair = CheckHair(env, emitter)
    cuthair = CutHair(env, emitter)
    reception = Reception(env, emitter, checkhair)

    # wire references
    checkhair.cuthair = cuthair
    checkhair.reception = reception
    cuthair.checkhair = checkhair

    def source_process():
        for t, _ev in schedule:
            if t < env.now:
                continue
            yield env.timeout(t - env.now)
            reception.arrive("newcust")

    env.process(source_process())

    # Run until simulation_time
    env.run(until=args.simulation_time)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
