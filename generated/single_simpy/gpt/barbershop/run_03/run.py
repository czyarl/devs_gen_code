#!/usr/bin/env python3
import argparse
import sys
import json
import logging
from collections import deque
import random  # allowed; not strictly required
import simpy

# Required by spec; program does not depend on it.
try:
    import xdevs  # type: ignore  # noqa: F401
except Exception:
    xdevs = None  # noqa: F841


def parse_time_to_seconds(hhmmssff: str) -> float:
    """
    Parse 'HH:MM:SS:mm' to seconds (float), where the last 'mm' is centiseconds.
    Example: 08:00:10:50 -> 28810.50 seconds.
    """
    parts = hhmmssff.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {hhmmssff!r}")
    hh, mm, ss, cs = (int(p) for p in parts)
    return hh * 3600 + mm * 60 + ss + cs / 100.0


class JSONEmitter:
    def __init__(self, out_stream):
        self.out = out_stream

    def _emit(self, obj: dict) -> None:
        self.out.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def state(self, t: float, model: str, field: str, value):
        self._emit({
            "time": float(t),
            "type": "state",
            "model": model,
            "field": field,
            "value": value,
        })

    def message(self, t: float, model: str, port: str, content: str):
        self._emit({
            "time": float(t),
            "type": "message",
            "model": model,
            "port": port,
            "content": content,
        })


class Reception:
    """
    Reception queue:
      - capacity 8
      - single-server check-in: 5s per customer
      - customer stays in queue while being checked-in
      - after 5s, waits until checkhair is available, then hands off and removes from queue
    """
    def __init__(self, env: simpy.Environment, emitter: JSONEmitter, checkhair, capacity: int = 8):
        self.env = env
        self.emitter = emitter
        self.checkhair = checkhair
        self.capacity = capacity

        self._queue = deque()
        self._arrival_wakeup = simpy.Event(env)
        self._next_customer_id = 1

        # optional: receive "done" notifications (not required for logic)
        self.done_in = simpy.Store(env)

        # Start processes
        self.env.process(self._run_server())
        self.env.process(self._run_done_sink())

    @property
    def queue_size(self) -> int:
        return len(self._queue)

    def arrive_new_customer(self) -> None:
        """Called at the scheduled arrival times."""
        if self.queue_size >= self.capacity:
            return  # ignore, no state change

        cust_id = self._next_customer_id
        self._next_customer_id += 1
        self._queue.append(cust_id)

        # State change: total customers in reception
        self.emitter.state(self.env.now, "reception", "total customers num", self.queue_size)

        # wake server if it was waiting
        if not self._arrival_wakeup.triggered:
            self._arrival_wakeup.succeed()
        self._arrival_wakeup = simpy.Event(self.env)

    def _wait_for_nonempty_queue(self):
        while self.queue_size == 0:
            yield self._arrival_wakeup

    def _run_server(self):
        while True:
            yield from self._wait_for_nonempty_queue()

            # "Process" the first customer in queue for 5 seconds, but keep them in queue.
            cust_id = self._queue[0]
            yield self.env.timeout(5.0)

            # Wait until checkhair is available to accept a customer
            yield self.checkhair.available_event

            # Handoff: remove customer from reception queue, send to checkhair
            if self.queue_size == 0 or self._queue[0] != cust_id:
                # Should not happen, but avoid crashing; restart loop.
                continue

            self._queue.popleft()
            self.emitter.state(self.env.now, "reception", "total customers num", self.queue_size)

            self.emitter.message(self.env.now, "reception", "cust", "newcust")
            yield self.checkhair.in_from_reception.put(cust_id)

    def _run_done_sink(self):
        while True:
            _ = yield self.done_in.get()
            # No stdout output here (sender already emits the message event).


class CheckHair:
    """
    Hair inspection phase:
      - accepts from reception when available
      - 7s consultation
      - forwards to cuthair
      - waits for done signal from cuthair
      - then notifies reception and becomes available again
    """
    def __init__(self, env: simpy.Environment, emitter: JSONEmitter):
        self.env = env
        self.emitter = emitter

        self.in_from_reception = simpy.Store(env)
        self.to_cuthair = simpy.Store(env)
        self.done_from_cuthair = simpy.Store(env)
        self.to_reception = None  # will be wired after Reception is created

        self._busy = False
        self.available_event = simpy.Event(env)
        self.available_event.succeed()  # initially available

        self.env.process(self._run())

    def _set_busy(self, busy: bool):
        self._busy = busy
        if busy:
            # replace with an unsucceeded event so others can wait
            self.available_event = simpy.Event(self.env)
        else:
            # succeed current event (if not already) to signal availability
            if not self.available_event.triggered:
                self.available_event.succeed()

    def _run(self):
        while True:
            cust_id = yield self.in_from_reception.get()
            self._set_busy(True)

            # State: start inspection (customer status)
            self.emitter.state(self.env.now, "checkhair", "customer", "newcust")

            # Process inspection
            yield self.env.timeout(7.0)

            # Forward to cutting
            self.emitter.message(self.env.now, "checkhair", "to_cut", "newcust")
            yield self.to_cuthair.put(cust_id)

            # Wait for cutting to finish
            done_id = yield self.done_from_cuthair.get()
            _ = done_id  # single-customer pipeline, id not used in stdout

            # State: inspection acknowledges completion after cutting
            self.emitter.state(self.env.now, "checkhair", "customer", "done")

            # Notify reception full service complete
            self.emitter.message(self.env.now, "checkhair", "to_reception", "done")
            if self.to_reception is not None:
                yield self.to_reception.put("done")

            # Available again
            self._set_busy(False)


class CutHair:
    """
    Hair cutting phase:
      - accepts from checkhair
      - 20s cutting
      - increments total done counter
      - signals done back to checkhair
    """
    def __init__(self, env: simpy.Environment, emitter: JSONEmitter, checkhair: CheckHair):
        self.env = env
        self.emitter = emitter
        self.checkhair = checkhair

        self.total_done = 0
        self.env.process(self._run())

    def _run(self):
        while True:
            cust_id = yield self.checkhair.to_cuthair.get()
            yield self.env.timeout(20.0)

            self.total_done += 1
            self.emitter.state(self.env.now, "cuthair", "total customer done", self.total_done)

            self.emitter.message(self.env.now, "cuthair", "out", "done")
            yield self.checkhair.done_from_cuthair.put(cust_id)


def build_schedule_from_stdin(logger: logging.Logger):
    """
    Reads ALL stdin lines and returns a sorted list of (time_seconds, event_name).
    Only supports event_name == 'newcust'.
    """
    schedule = []
    for line_no, raw in enumerate(sys.stdin, start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            time_part, event_name = line.split()
        except ValueError:
            logger.warning("Skipping invalid line %d (expected 2 tokens): %r", line_no, line)
            continue

        if event_name != "newcust":
            logger.warning("Skipping unsupported event %r on line %d", event_name, line_no)
            continue

        try:
            t = parse_time_to_seconds(time_part)
        except Exception as e:
            logger.warning("Skipping invalid time on line %d: %r (%s)", line_no, time_part, e)
            continue

        schedule.append((t, event_name))

    schedule.sort(key=lambda x: x[0])
    return schedule


def feeder_process(env: simpy.Environment, schedule, reception: Reception):
    last_t = 0.0
    for t, _name in schedule:
        if t < last_t:
            # schedule is sorted, but keep safe
            t = last_t
        yield env.timeout(t - last_t)
        reception.arrive_new_customer()
        last_t = t


def main():
    parser = argparse.ArgumentParser(description="Barbershop discrete-event simulation (SimPy).")
    parser.add_argument("--simulation_time", type=float, default=1000000.0,
                        help="Total simulation time in seconds (default: 1000000.0).")
    args = parser.parse_args()

    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s:%(message)s")
    logger = logging.getLogger("barbershop")

    # Requirement: consume ALL stdin lines BEFORE starting the simulation loop.
    schedule = build_schedule_from_stdin(logger)
    logger.info("Loaded %d scheduled events from stdin.", len(schedule))

    env = simpy.Environment(initial_time=0.0)
    emitter = JSONEmitter(sys.stdout)

    # Build modules and wire them
    checkhair = CheckHair(env, emitter)
    reception = Reception(env, emitter, checkhair, capacity=8)
    checkhair.to_reception = reception.done_in
    _cuthair = CutHair(env, emitter, checkhair)

    # Start feeder after building full schedule
    env.process(feeder_process(env, schedule, reception))

    # Run: SimPy stops when event queue empties, even if simulation_time is large.
    try:
        env.run(until=args.simulation_time)
    except Exception as e:
        logger.error("Simulation error: %s", e)
        raise


if __name__ == "__main__":
    main()