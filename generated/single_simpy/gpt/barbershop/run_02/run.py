#!/usr/bin/env python3
import argparse
import sys
import json
import logging
from collections import deque
import simpy

# Mentioned as available in the environment. Not required for this SimPy implementation.
try:
    import xdevs  # noqa: F401
except Exception:  # pragma: no cover
    xdevs = None


# ----------------------------
# Utilities
# ----------------------------

def parse_time_hhmmsscc(s: str) -> float:
    """
    Parse 'HH:MM:SS:mm' into seconds as float.
    Interprets the last field as centiseconds (1/100 s).
    """
    parts = s.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {s!r}, expected HH:MM:SS:mm")
    hh, mm, ss, cc = (int(p) for p in parts)
    return hh * 3600.0 + mm * 60.0 + ss + (cc / 100.0)


class JSONLLogger:
    """
    Emits ONLY JSONL to stdout. Any diagnostics should go to stderr via logging.
    """
    def __init__(self, out_stream):
        self.out = out_stream

    def emit_state(self, time: float, model: str, field: str, value):
        obj = {
            "time": float(time),
            "type": "state",
            "model": model,
            "field": field,
            "value": value,
        }
        self.out.write(json.dumps(obj) + "\n")

    def emit_message(self, time: float, model: str, port: str, content: str):
        obj = {
            "time": float(time),
            "type": "message",
            "model": model,
            "port": port,
            "content": content,
        }
        self.out.write(json.dumps(obj) + "\n")


# ----------------------------
# Simulation Modules
# ----------------------------

class Reception:
    """
    Reception Desk:
      - Queue capacity: 8
      - Processes 1 customer at a time: 5 seconds check-in
      - After check-in, hands off to checkhair only when checkhair is available.
    """
    MODEL = "reception"
    QUEUE_CAPACITY = 8
    CHECKIN_TIME = 5.0

    def __init__(self, env: simpy.Environment, logger: JSONLLogger):
        self.env = env
        self.logger = logger

        self.queue = deque()
        self._new_arrival_event = env.event()

        # Optional store to receive completion notifications (not used for logic)
        self.notifications = simpy.Store(env)

        # Start receptionist process
        self.env.process(self._run_receptionist())
        self.env.process(self._drain_notifications())

    def _signal_new_arrival(self):
        if not self._new_arrival_event.triggered:
            self._new_arrival_event.succeed()
        self._new_arrival_event = self.env.event()

    def arrive(self, cust: str):
        """External arrival event."""
        if len(self.queue) >= self.QUEUE_CAPACITY:
            return  # ignore, no state change
        self.queue.append(cust)
        self.logger.emit_state(self.env.now, self.MODEL, "total customers num", len(self.queue))
        self._signal_new_arrival()

    def notify_done(self, content: str):
        """Called when checkhair signals completion."""
        # No reception state change specified for this; keep for completeness.
        self.notifications.put(content)

    def _drain_notifications(self):
        while True:
            _ = yield self.notifications.get()
            # Intentionally no stdout output here (message already logged by sender).

    def _run_receptionist(self):
        # checkhair reference will be injected after construction
        while True:
            if not self.queue:
                yield self._new_arrival_event
                continue

            # Process the first customer for exactly 5 seconds, still in queue.
            yield self.env.timeout(self.CHECKIN_TIME)

            # After check-in, wait until checkhair is available, then hand off.
            # The receptionist is blocked here and cannot process the next customer.
            yield self.checkhair.available_event

            # Claim availability immediately to prevent any concurrent sender (even though we only have one)
            self.checkhair.claim()

            cust = self.queue[0]
            self.logger.emit_message(self.env.now, self.MODEL, "cust", "newcust")
            yield self.checkhair.incoming.put(cust)

            # Remove from queue after successful send
            self.queue.popleft()
            self.logger.emit_state(self.env.now, self.MODEL, "total customers num", len(self.queue))


class CheckHair:
    """
    Hair Inspection Phase:
      - 1 customer at a time
      - 7 seconds consultation
      - Forwards to cuthair
      - Waits for done from cuthair
      - Notifies reception done
      - Only then becomes available again
    """
    MODEL = "checkhair"
    CONSULT_TIME = 7.0

    def __init__(self, env: simpy.Environment, logger: JSONLLogger):
        self.env = env
        self.logger = logger

        self.incoming = simpy.Store(env)   # customers from reception
        self.done_in = simpy.Store(env)    # 'done' signals from cuthair

        self.available = True
        self.available_event = env.event()
        self.available_event.succeed()  # initially available

        self.env.process(self._run())

    def claim(self):
        """Mark as busy from the perspective of senders (reception)."""
        if self.available:
            self.available = False
            self.available_event = self.env.event()

    def _set_available(self):
        self.available = True
        if not self.available_event.triggered:
            self.available_event.succeed()

    def _run(self):
        while True:
            cust = yield self.incoming.get()

            # Processing start
            self.logger.emit_state(self.env.now, self.MODEL, "customer", "newcust")
            yield self.env.timeout(self.CONSULT_TIME)

            # Forward to cutting
            self.logger.emit_message(self.env.now, self.MODEL, "to_cut", "newcust")
            yield self.cuthair.incoming.put(cust)

            # Wait for cutting completion
            _done = yield self.done_in.get()

            # Mark completion for this customer
            self.logger.emit_state(self.env.now, self.MODEL, "customer", "done")

            # Notify reception before becoming available again
            self.logger.emit_message(self.env.now, self.MODEL, "to_reception", "done")
            self.reception.notify_done("done")

            # Now available for next customer
            self._set_available()


class CutHair:
    """
    Hair Cutting Phase:
      - 1 customer at a time
      - 20 seconds cutting
      - Signals 'done' to checkhair
      - Tracks cumulative completed cuts
    """
    MODEL = "cuthair"
    CUT_TIME = 20.0

    def __init__(self, env: simpy.Environment, logger: JSONLLogger):
        self.env = env
        self.logger = logger

        self.incoming = simpy.Store(env)  # customers from checkhair
        self.total_done = 0

        self.env.process(self._run())

    def _run(self):
        while True:
            _cust = yield self.incoming.get()
            yield self.env.timeout(self.CUT_TIME)

            self.total_done += 1
            self.logger.emit_state(self.env.now, self.MODEL, "total customer done", self.total_done)

            self.logger.emit_message(self.env.now, self.MODEL, "out", "done")
            yield self.checkhair.done_in.put("done")


# ----------------------------
# Scheduling input events
# ----------------------------

def schedule_arrivals(env: simpy.Environment, reception: Reception, schedule):
    """
    schedule: list of (time, event_name)
    Only event_name == 'newcust' supported.
    """
    def _arrival_at(t: float):
        yield env.timeout(max(0.0, t - env.now))
        reception.arrive("newcust")

    for t, name in schedule:
        if name != "newcust":
            continue
        env.process(_arrival_at(t))


# ----------------------------
# Main
# ----------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="run.py")
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=1000000.0,
        help="Total simulation time in seconds (default: 1000000.0)."
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s:%(name)s:%(message)s"
    )
    log = logging.getLogger("barbershop")

    # Consume ALL stdin lines to build schedule BEFORE starting simulation loop
    schedule = []
    for raw in sys.stdin.read().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            time_str, event_name = line.split()
            t = parse_time_hhmmsscc(time_str)
            schedule.append((t, event_name))
        except Exception as e:
            log.warning("Skipping invalid input line %r: %s", raw, e)

    schedule.sort(key=lambda x: x[0])
    log.info("Loaded %d scheduled events", len(schedule))

    env = simpy.Environment()
    jlog = JSONLLogger(sys.stdout)

    # Build modules
    reception = Reception(env, jlog)
    checkhair = CheckHair(env, jlog)
    cuthair = CutHair(env, jlog)

    # Wire references
    reception.checkhair = checkhair
    checkhair.cuthair = cuthair
    checkhair.reception = reception
    cuthair.checkhair = checkhair

    # Schedule all arrivals before starting simulation loop
    schedule_arrivals(env, reception, schedule)

    # Run simulation (simulation time, not real time)
    env.run(until=args.simulation_time)

    # Ensure stdout flush
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())