#!/usr/bin/env python3
import argparse
import sys
import json
import logging
from collections import deque
import simpy

# Optional import (not required for the implementation, but requested in requirements)
try:
    import xdevs  # type: ignore  # noqa: F401
except Exception:
    xdevs = None  # noqa: F841


# -----------------------------
# Logging (stderr only)
# -----------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:%(name)s:%(message)s",
    stream=sys.stderr,
)
LOG = logging.getLogger("barbershop-sim")


# -----------------------------
# JSONL emitters (stdout only)
# -----------------------------
def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")


def emit_state(env_now: float, model: str, field: str, value):
    emit(
        {
            "time": float(env_now),
            "type": "state",
            "model": model,
            "field": field,
            "value": value,
        }
    )


def emit_message(env_now: float, model: str, port: str, content: str):
    # content must be among ["newcust", "done"]
    emit(
        {
            "time": float(env_now),
            "type": "message",
            "model": model,
            "port": port,
            "content": content,
        }
    )


# -----------------------------
# Input parsing
# -----------------------------
def parse_timecode_to_seconds(s: str) -> float:
    """
    Parse HH:MM:SS:mm where mm is centiseconds (0-99), return absolute seconds from 00:00:00.00.
    """
    parts = s.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid timecode (expected HH:MM:SS:mm): {s!r}")
    hh, mm, ss, cs = (int(p) for p in parts)
    return hh * 3600.0 + mm * 60.0 + ss * 1.0 + (cs / 100.0)


def read_schedule_from_stdin() -> list[tuple[float, str]]:
    """
    Read ALL stdin lines, parse, and return list of (absolute_time_seconds, event_name).
    Only event_name 'newcust' is supported.
    """
    events: list[tuple[float, str]] = []
    for line_no, raw in enumerate(sys.stdin.read().splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        try:
            time_str, event_name = line.split()
        except ValueError:
            LOG.warning("Ignoring malformed line %d: %r", line_no, raw)
            continue
        if event_name != "newcust":
            LOG.warning("Ignoring unsupported event on line %d: %r", line_no, raw)
            continue
        try:
            t_abs = parse_timecode_to_seconds(time_str)
        except Exception as e:
            LOG.warning("Ignoring bad timecode on line %d (%r): %s", line_no, raw, e)
            continue
        events.append((t_abs, event_name))
    return events


# -----------------------------
# Simulation modules
# -----------------------------
class Reception:
    """
    Reception Desk:
      - waiting area capacity = 8
      - processes 1 customer at a time, 5 seconds check-in
      - after 5 seconds, if checkhair is available, send customer; else keep waiting
    """

    def __init__(self, env: simpy.Environment, checkhair, done_store: simpy.Store):
        self.env = env
        self.model = "reception"
        self.checkhair = checkhair
        self.done_store = done_store

        self.queue = deque()
        self.capacity = 8
        self.processing = False

        # For waking up the main loop when first customer arrives
        self._queue_nonempty_event = env.event()

        # Trackable variable
        self.total_customers_num = 0

        self._proc_main = env.process(self._run())
        self._proc_done = env.process(self._consume_done_notifications())

    def _set_total_customers(self, new_val: int):
        if new_val != self.total_customers_num:
            self.total_customers_num = new_val
            emit_state(self.env.now, self.model, "total customers num", self.total_customers_num)

    def arrive(self, cust_id: int):
        # Arrival: accept only if queue < 8
        if len(self.queue) >= self.capacity:
            return
        was_empty = (len(self.queue) == 0)
        self.queue.append(cust_id)
        self._set_total_customers(len(self.queue))
        if was_empty and not self._queue_nonempty_event.triggered:
            self._queue_nonempty_event.succeed()

    def _wait_for_queue_nonempty(self):
        if len(self.queue) > 0:
            return self.env.timeout(0)
        # reset and wait
        self._queue_nonempty_event = self.env.event()
        return self._queue_nonempty_event

    def _run(self):
        while True:
            # wait for at least one customer
            yield self._wait_for_queue_nonempty()

            # process first in queue
            if len(self.queue) == 0:
                continue

            self.processing = True
            first_id = self.queue[0]

            # Hold customer for exactly 5 seconds (still in queue)
            yield self.env.timeout(5.0)

            # Handoff: wait until checkhair is available
            yield self.checkhair.available_event

            # Remove from queue at send time
            # (Still FIFO; ensure the same customer is sent)
            if len(self.queue) == 0:
                self.processing = False
                continue
            send_id = self.queue.popleft()
            # If something unexpected happened, still proceed with the popped customer
            _ = first_id  # keep variable for readability

            self._set_total_customers(len(self.queue))

            # Send to checkhair
            emit_message(self.env.now, self.model, "cust", "newcust")
            yield self.checkhair.in_store.put(send_id)

            self.processing = False

    def _consume_done_notifications(self):
        while True:
            # Notification from checkhair: service fully complete
            _cust_id = yield self.done_store.get()
            # No tracked reception variable changes here per spec


class CheckHair:
    """
    Hair Inspection:
      - 1 customer at a time, 7 seconds consultation
      - then forward to cuthair
      - wait for "done" from cuthair
      - then notify reception and only then become available again
    """

    def __init__(self, env: simpy.Environment, cut_in_store: simpy.Store, done_from_cut_store: simpy.Store, to_reception_done_store: simpy.Store):
        self.env = env
        self.model = "checkhair"

        self.in_store = simpy.Store(env, capacity=1)
        self.cut_in_store = cut_in_store
        self.done_from_cut_store = done_from_cut_store
        self.to_reception_done_store = to_reception_done_store

        self.busy = False
        self.available_event = env.event()
        self.available_event.succeed()  # initially available

        self._proc = env.process(self._run())

    def _set_available(self, is_available: bool):
        if is_available:
            self.busy = False
            if not self.available_event.triggered:
                self.available_event.succeed()
        else:
            self.busy = True
            # create a fresh, not-yet-triggered event to represent "not available"
            self.available_event = self.env.event()

    def _run(self):
        while True:
            # ensure available while waiting for a new customer
            self._set_available(True)

            cust_id = yield self.in_store.get()
            self._set_available(False)

            # State change: start inspection
            emit_state(self.env.now, self.model, "customer", "newcust")

            # Process 7 seconds
            yield self.env.timeout(7.0)

            # Forward to cutting
            emit_message(self.env.now, self.model, "to_cut", "newcust")
            yield self.cut_in_store.put(cust_id)

            # Wait for done signal from cutter
            done_id = yield self.done_from_cut_store.get()
            _ = done_id  # identity not required for outputs

            # State change: customer done cutting
            emit_state(self.env.now, self.model, "customer", "done")

            # Notify reception that full service is complete
            emit_message(self.env.now, self.model, "to_reception", "done")
            yield self.to_reception_done_store.put(cust_id)

            # Only after notification does it become available again (loop top)


class CutHair:
    """
    Hair Cutting:
      - 1 customer at a time, 20 seconds cutting
      - signal done back to checkhair
    """

    def __init__(self, env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store):
        self.env = env
        self.model = "cuthair"

        self.in_store = in_store
        self.out_store = out_store

        self.busy = False

        self.total_customer_done = 0
        self._proc = env.process(self._run())

    def _inc_done(self):
        self.total_customer_done += 1
        emit_state(self.env.now, self.model, "total customer done", self.total_customer_done)

    def _run(self):
        while True:
            cust_id = yield self.in_store.get()
            self.busy = True

            # Process 20 seconds
            yield self.env.timeout(20.0)

            # Completion
            self._inc_done()
            emit_message(self.env.now, self.model, "out", "done")
            yield self.out_store.put(cust_id)

            self.busy = False


# -----------------------------
# Simulation orchestration
# -----------------------------
def schedule_arrivals(env: simpy.Environment, reception: Reception, arrivals: list[tuple[float, str]]):
    """
    arrivals: list of (sim_time, 'newcust'), already normalized.
    """
    def one_arrival(at_t: float, cust_id: int):
        yield env.timeout(max(0.0, at_t - env.now))
        reception.arrive(cust_id)

    for i, (t, name) in enumerate(arrivals, start=1):
        if name != "newcust":
            continue
        env.process(one_arrival(t, i))


def build_normalized_schedule(abs_events: list[tuple[float, str]]) -> list[tuple[float, str]]:
    if not abs_events:
        return []
    t0 = min(t for t, _ in abs_events)
    normalized = [(t - t0, name) for (t, name) in abs_events]
    normalized.sort(key=lambda x: x[0])
    return normalized


def run_simulation(simulation_time: float, schedule: list[tuple[float, str]]):
    env = simpy.Environment()

    # Communication channels
    cut_in = simpy.Store(env)        # checkhair -> cuthair
    cut_done = simpy.Store(env)      # cuthair -> checkhair
    reception_done = simpy.Store(env)  # checkhair -> reception

    # Modules
    cuthair = CutHair(env, in_store=cut_in, out_store=cut_done)
    checkhair = CheckHair(env, cut_in_store=cut_in, done_from_cut_store=cut_done, to_reception_done_store=reception_done)
    reception = Reception(env, checkhair=checkhair, done_store=reception_done)

    # Schedule all arrivals BEFORE starting simulation loop
    schedule_arrivals(env, reception, schedule)

    last_arrival_time = max((t for t, _ in schedule), default=0.0)

    finished = env.event()

    def monitor_finish():
        # End when: no more arrivals pending (time >= last arrival) AND system empty/idle.
        while True:
            if env.now >= last_arrival_time:
                queues_empty = (len(reception.queue) == 0 and len(checkhair.in_store.items) == 0 and len(cut_in.items) == 0)
                modules_idle = (not reception.processing and not checkhair.busy and not cuthair.busy)
                # also ensure no pending completion notifications in transit (they don't affect state, but indicate activity)
                comms_empty = (len(reception_done.items) == 0 and len(cut_done.items) == 0)
                if queues_empty and modules_idle and comms_empty:
                    if not finished.triggered:
                        finished.succeed()
                    return
            yield env.timeout(0.1)

    env.process(monitor_finish())

    # Stop at either natural finish or simulation_time
    stopper = env.timeout(float(simulation_time))
    until = simpy.events.AnyOf(env, [finished, stopper])
    env.run(until=until)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Barbershop discrete-event simulation (simpy).")
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=1000000.0,
        help="Total simulation time in seconds (default: 1000000.0)",
    )
    args = parser.parse_args(argv)

    abs_events = read_schedule_from_stdin()
    schedule = build_normalized_schedule(abs_events)

    LOG.info("Loaded %d scheduled events from stdin.", len(schedule))
    if schedule:
        LOG.info("First event at t=%.2f, last at t=%.2f (normalized).", schedule[0][0], schedule[-1][0])
    else:
        LOG.info("No events provided; simulation may end immediately.")

    run_simulation(simulation_time=args.simulation_time, schedule=schedule)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())