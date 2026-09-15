#!/usr/bin/env python3
import argparse
import sys
import json
import logging
import random
import time
import math
from collections import deque

# Allowed imports (some unused but permitted by requirements)
import simpy  # noqa: F401

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

PROCESSING_DELAY = 10.0


def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )


def seed_rng():
    ns = time.time_ns()
    random.seed(ns)


def parse_timestamp_to_seconds(ts: str) -> float:
    # Format: HH:MM:SS:mmm
    parts = ts.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid timestamp format: {ts!r}")
    hh, mm, ss, mmm = parts
    h = int(hh)
    m = int(mm)
    s = int(ss)
    ms = int(mmm)
    return float(h * 3600 + m * 60 + s) + (ms / 1000.0)


def jsonl_event(t: float, model: str, event: str, data: dict):
    # MUST print only JSONL objects to stdout
    sys.stdout.write(json.dumps({"time": float(t), "model": model, "event": event, "data": data}) + "\n")
    sys.stdout.flush()


class BalanceStore:
    def __init__(self, initial_balance: int = 3000):
        self.balance = int(initial_balance)


class BaseServerAtomic(Atomic):
    """
    Single-server FIFO with deterministic service delay.
    Uses internal self._time and self._sigma to compute event timestamps for logging.
    """
    def __init__(self, name: str, parent: Coupled | None, delay: float = PROCESSING_DELAY):
        super().__init__(name)
        self.parent = parent
        self.delay = float(delay)

        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out"))

        self._time = 0.0
        self._sigma = math.inf
        self._phase = "PASSIVE"

        self._queue = deque()
        self._busy = False
        self._current = None  # current job/message
        self._out_msg = None  # message to emit on completion (or None)
        self._log_event = None  # (event_name, data_dict) to print at completion

    def initialize(self):
        self._time = 0.0
        self._busy = False
        self._current = None
        self._out_msg = None
        self._log_event = None
        self._queue.clear()
        self._set_phase("PASSIVE", math.inf)

    def _set_phase(self, phase: str, sigma: float):
        self._phase = phase
        self._sigma = float(sigma)
        self.hold_in(phase, sigma)

    def _lambda_time(self) -> float:
        # lambda happens at t_last + sigma; our _time tracks t_last
        if math.isinf(self._sigma):
            return float(self._time)
        return float(self._time + self._sigma)

    def _consume_incoming(self):
        vals = list(self.input["in"].values)
        try:
            self.input["in"].values.clear()
        except Exception:
            pass
        return vals

    def _start_service_if_possible(self):
        if self._busy:
            return
        if not self._queue:
            self._set_phase("PASSIVE", math.inf)
            return

        self._busy = True
        self._current = self._queue.popleft()
        self._prepare_on_start(self._current)
        self._set_phase("BUSY", self.delay)

    # Overridden by subclasses
    def _prepare_on_start(self, msg: dict):
        self._out_msg = msg
        self._log_event = None

    def lambdaf(self):
        t = self._lambda_time()

        # Print required log event at completion (if any)
        if self._log_event is not None:
            ev_name, ev_data = self._log_event
            jsonl_event(t, self.name, ev_name, ev_data)

        # Emit message (if any)
        if self._out_msg is not None:
            self.output["out"].add(self._out_msg)

    def deltint(self):
        # Advance model time to internal event time
        if not math.isinf(self._sigma):
            self._time += self._sigma

        if self._phase == "BUSY":
            # Job completed
            self._busy = False
            self._current = None
            self._out_msg = None
            self._log_event = None

            # Start next if queued
            self._start_service_if_possible()
        else:
            self._set_phase("PASSIVE", math.inf)

    def deltext(self, e):
        # Advance time to current external event time
        self._time += float(e)

        incoming = self._consume_incoming()
        if incoming:
            for msg in incoming:
                self._queue.append(msg)

        if self._phase == "BUSY":
            # Continue current service; adjust remaining time
            remaining = max(0.0, self._sigma - float(e))
            self._set_phase("BUSY", remaining)
        else:
            self._start_service_if_possible()

    def exit(self):
        # No stdout output here; keep debug on stderr only
        return


class InputReader1(Atomic):
    """
    Reads stdin during initialize, then emits requests at their timestamps.
    Logs:
      - start at t=0
      - input at each request timestamp
    """
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_out_port(Port(dict, "out"))

        self._time = 0.0
        self._sigma = math.inf
        self._phase = "PASSIVE"

        self._events = []  # list of dict {t, valid, invalid, id}
        self._idx = 0
        self._next_emit_time = None

        # For lambdaf batch output
        self._emit_batch = []

    def _set_phase(self, phase: str, sigma: float):
        self._phase = phase
        self._sigma = float(sigma)
        self.hold_in(phase, sigma)

    def _lambda_time(self) -> float:
        if math.isinf(self._sigma):
            return float(self._time)
        return float(self._time + self._sigma)

    def initialize(self):
        self._time = 0.0
        self._idx = 0
        self._events = []
        self._emit_batch = []
        self._next_emit_time = None

        # Read stdin line-by-line and parse requests
        req_id = 0
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            if "#" in line:
                line = line.split("#", 1)[0].strip()
                if not line:
                    continue
            parts = line.split()
            if len(parts) != 3:
                logging.warning("Skipping invalid input line: %r", raw.rstrip("\n"))
                continue
            ts_s, valid_s, invalid_s = parts
            try:
                t = parse_timestamp_to_seconds(ts_s)
                valid = int(valid_s)
                invalid = int(invalid_s)
            except Exception as ex:
                logging.warning("Skipping unparsable input line %r (%s)", raw.rstrip("\n"), ex)
                continue
            self._events.append({"t": float(t), "valid": valid, "invalid": invalid, "id": req_id})
            req_id += 1

        # Stable sort by timestamp, preserving read order for ties
        self._events.sort(key=lambda d: (d["t"], d["id"]))

        # First, emit "start" at t=0
        self._set_phase("START", 0.0)

    def lambdaf(self):
        t = self._lambda_time()

        if self._phase == "START":
            jsonl_event(t, self.name, "start", {})
            return

        if self._phase == "EMIT":
            # Emit all events scheduled at this time
            for ev in self._emit_batch:
                jsonl_event(t, self.name, "input", {"valid": int(ev["valid"]), "invalid": int(ev["invalid"])})
                # Forward to AAM with id preserved (not part of log schema)
                self.output["out"].add({"id": ev["id"], "valid": int(ev["valid"]), "invalid": int(ev["invalid"])})
            return

    def deltint(self):
        # Advance to internal time
        if not math.isinf(self._sigma):
            self._time += self._sigma

        if self._phase == "START":
            # Schedule first EMIT
            if self._idx >= len(self._events):
                self._set_phase("PASSIVE", math.inf)
                return
            next_t = self._events[self._idx]["t"]
            sigma = max(0.0, next_t - self._time)
            self._set_phase("EMIT", sigma)
            return

        if self._phase == "EMIT":
            # We are now at emit time; prepare next batch time
            # Advance idx past what we emitted
            if self._idx < len(self._events):
                current_t = self._events[self._idx]["t"]
            else:
                current_t = None

            # Safety: current_t should match _time
            # Move idx to first event after current time
            while self._idx < len(self._events) and self._events[self._idx]["t"] == self._time:
                self._idx += 1

            if self._idx >= len(self._events):
                self._emit_batch = []
                self._set_phase("PASSIVE", math.inf)
                return

            next_t = self._events[self._idx]["t"]
            sigma = max(0.0, next_t - self._time)
            self._set_phase("EMIT", sigma)
            return

        self._set_phase("PASSIVE", math.inf)

    def deltext(self, e):
        # No external inputs expected; just advance time
        self._time += float(e)
        # keep current phase and sigma adjusted if needed
        if self._phase in ("START", "EMIT"):
            remaining = max(0.0, self._sigma - float(e))
            self._set_phase(self._phase, remaining)
        else:
            self._set_phase("PASSIVE", math.inf)

    def exit(self):
        return

    def _prepare_emit_batch(self, emit_time: float):
        batch = []
        j = self._idx
        while j < len(self._events) and self._events[j]["t"] == emit_time:
            batch.append(self._events[j])
            j += 1
        self._emit_batch = batch

    def hold_in(self, phase, sigma):
        # Intercept to prepare batch before the EMIT lambda
        if phase == "EMIT":
            emit_time = self._time + float(sigma)
            self._prepare_emit_batch(emit_time)
        super().hold_in(phase, sigma)


class AAM1(BaseServerAtomic):
    def _prepare_on_start(self, msg: dict):
        invalid = int(msg.get("invalid", 0))
        if invalid == 1:
            self._out_msg = None
            self._log_event = ("logout", {})
        else:
            self._out_msg = {"id": msg.get("id")}
            self._log_event = ("account_generated", {})


class ANV1(BaseServerAtomic):
    def _prepare_on_start(self, msg: dict):
        passed = 1 if random.random() < 0.5 else 0
        failed = 1 - passed
        self._log_event = ("verification", {"pass": int(passed), "fail": int(failed)})
        if passed:
            self._out_msg = {"id": msg.get("id")}
        else:
            self._out_msg = None


class PV1(BaseServerAtomic):
    def _prepare_on_start(self, msg: dict):
        # Geometric trials until success (p=0.5)
        attempts = 1
        while random.random() >= 0.5:
            attempts += 1
        self._log_event = ("verification", {"success": 1, "attempts": int(attempts)})
        self._out_msg = {"id": msg.get("id")}


class BPM1(BaseServerAtomic):
    def __init__(self, name: str, parent: Coupled | None, balance_store: BalanceStore, delay: float = PROCESSING_DELAY):
        super().__init__(name, parent, delay=delay)
        self._store = balance_store

    def _prepare_on_start(self, msg: dict):
        bal = int(self._store.balance)
        amount = random.randint(0, 40)
        if bal <= 0:
            amount = 0
        else:
            amount = min(amount, bal)
        self._log_event = ("bill", {"amount": int(amount)})
        self._out_msg = {"id": msg.get("id"), "amount": int(amount)}


class TPM1(BaseServerAtomic):
    def __init__(self, name: str, parent: Coupled | None, balance_store: BalanceStore, delay: float = PROCESSING_DELAY):
        super().__init__(name, parent, delay=delay)
        self._store = balance_store
        self._count = 0
        self._pending_remaining = int(self._store.balance)

    def initialize(self):
        super().initialize()
        self._count = 0
        self._pending_remaining = int(self._store.balance)

    def _prepare_on_start(self, msg: dict):
        amount = int(msg.get("amount", 0))
        bal = int(self._store.balance)
        if amount > bal:
            amount = bal
        remaining = bal - amount
        # Precompute for logging; commit on completion (deltint)
        self._pending_remaining = int(remaining)
        self._log_event = ("transaction", {"remaining": int(remaining), "count": int(self._count + 1)})
        self._out_msg = None

    def deltint(self):
        # Before completing, commit balance/count if we were busy
        was_busy = (self._phase == "BUSY")
        super().deltint()
        if was_busy:
            self._store.balance = int(self._pending_remaining)
            self._count += 1


class IOBSSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        store = BalanceStore(initial_balance=3000)

        input_reader = InputReader1("input_reader1", parent=self)
        aam = AAM1("AAM1", parent=self, delay=PROCESSING_DELAY)
        anv = ANV1("ANV1", parent=self, delay=PROCESSING_DELAY)
        pv = PV1("PV1", parent=self, delay=PROCESSING_DELAY)
        bpm = BPM1("BPM1", parent=self, balance_store=store, delay=PROCESSING_DELAY)
        tpm = TPM1("TPM1", parent=self, balance_store=store, delay=PROCESSING_DELAY)

        self.add_component(input_reader)
        self.add_component(aam)
        self.add_component(anv)
        self.add_component(pv)
        self.add_component(bpm)
        self.add_component(tpm)

        self.add_coupling(input_reader.output["out"], aam.input["in"])
        self.add_coupling(aam.output["out"], anv.input["in"])
        self.add_coupling(anv.output["out"], pv.input["in"])
        self.add_coupling(pv.output["out"], bpm.input["in"])
        self.add_coupling(bpm.output["out"], tpm.input["in"])


def main():
    setup_logging()
    seed_rng()

    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args()

    root = IOBSSystem(name="system", parent=None)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(float(args.simulation_time))


if __name__ == "__main__":
    main()