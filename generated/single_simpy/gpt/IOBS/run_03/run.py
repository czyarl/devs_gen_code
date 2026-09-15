#!/usr/bin/env python3
# run.py

import argparse
import sys
import json
import logging
import random
import time
from dataclasses import dataclass
import simpy

# Imported as requested (not strictly used in this SimPy implementation)
try:
    import xdevs  # noqa: F401
except Exception:
    xdevs = None


# ----------------------------
# Utilities
# ----------------------------

def setup_logging() -> logging.Logger:
    logger = logging.getLogger("iobs_sim")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def emit(env: simpy.Environment, model: str, event: str, data: dict) -> None:
    obj = {
        "time": float(env.now),
        "model": model,
        "event": event,
        "data": data,
    }
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def parse_timestamp_to_seconds(ts: str) -> float:
    # Format: HH:MM:SS:mmm
    parts = ts.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid timestamp format: {ts!r}")
    hh = int(parts[0])
    mm = int(parts[1])
    ss = int(parts[2])
    mmm = int(parts[3])
    return hh * 3600.0 + mm * 60.0 + ss * 1.0 + (mmm / 1000.0)


@dataclass(frozen=True)
class Request:
    seq: int
    t: float
    valid: int
    invalid: int


@dataclass
class AccountState:
    posted_balance: int = 3000   # balance after posted transactions (TPM)
    available_balance: int = 3000  # posted - reservations (for BPM capping)


# ----------------------------
# Models (pipeline stages)
# ----------------------------

class InputReader1:
    def __init__(self, env: simpy.Environment, out_store: simpy.Store, requests: list[Request], logger: logging.Logger):
        self.env = env
        self.out_store = out_store
        self.requests = requests
        self.logger = logger

    def run(self):
        emit(self.env, "input_reader1", "start", {})
        last_t = 0.0
        for req in self.requests:
            if req.t < last_t:
                # Keep deterministic behavior: still wait non-negative (do not go back in time).
                self.logger.warning("Non-monotonic input timestamps; clamping wait to 0.0 (req %s).", req.seq)
                wait = 0.0
            else:
                wait = req.t - last_t
            if wait > 0:
                yield self.env.timeout(wait)
            last_t = req.t

            emit(self.env, "input_reader1", "input", {"valid": int(req.valid), "invalid": int(req.invalid)})
            yield self.out_store.put(req)


class AAM1:
    def __init__(self, env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store):
        self.env = env
        self.in_store = in_store
        self.out_store = out_store

    def run(self):
        while True:
            req = yield self.in_store.get()
            # Processing delay
            yield self.env.timeout(10.0)

            if int(req.valid) == 1 and int(req.invalid) == 0:
                emit(self.env, "AAM1", "account_generated", {})
                yield self.out_store.put(req)
            else:
                emit(self.env, "AAM1", "logout", {})
                # End processing for this request


class ANV1:
    def __init__(self, env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store):
        self.env = env
        self.in_store = in_store
        self.out_store = out_store

    def run(self):
        while True:
            req = yield self.in_store.get()
            yield self.env.timeout(10.0)

            passed = 1 if random.random() < 0.5 else 0
            failed = 1 - passed
            emit(self.env, "ANV1", "verification", {"pass": int(passed), "fail": int(failed)})

            if passed:
                yield self.out_store.put(req)
            # else: end processing


class PV1:
    def __init__(self, env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store, max_attempts: int = 1000):
        self.env = env
        self.in_store = in_store
        self.out_store = out_store
        self.max_attempts = max_attempts

    def run(self):
        while True:
            req = yield self.in_store.get()

            attempts = 0
            success = 0
            while success == 0:
                attempts += 1
                # Each attempt consumes the model delay
                yield self.env.timeout(10.0)

                # 50% chance per attempt
                success = 1 if random.random() < 0.5 else 0

                # Hard safety to guarantee termination in finite event count
                if attempts >= self.max_attempts and success == 0:
                    success = 1

            emit(self.env, "PV1", "verification", {"success": 1, "attempts": int(attempts)})
            yield self.out_store.put(req)


class BPM1:
    def __init__(self, env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store,
                 account: AccountState, account_lock: simpy.Resource):
        self.env = env
        self.in_store = in_store
        self.out_store = out_store
        self.account = account
        self.account_lock = account_lock

    def run(self):
        while True:
            req = yield self.in_store.get()
            yield self.env.timeout(10.0)

            # Reserve funds so "remaining account balance" never goes negative even with pipeline overlap.
            with (yield self.account_lock.request()):
                max_amt = min(40, max(0, int(self.account.available_balance)))
                amount = random.randint(0, max_amt) if max_amt > 0 else 0
                self.account.available_balance -= int(amount)

            emit(self.env, "BPM1", "bill", {"amount": int(amount)})
            yield self.out_store.put((req, int(amount)))


class TPM1:
    def __init__(self, env: simpy.Environment, in_store: simpy.Store, account: AccountState, account_lock: simpy.Resource):
        self.env = env
        self.in_store = in_store
        self.account = account
        self.account_lock = account_lock
        self.count = 0

    def run(self):
        while True:
            req, amount = yield self.in_store.get()
            yield self.env.timeout(10.0)

            with (yield self.account_lock.request()):
                # Post the transaction
                self.account.posted_balance -= int(amount)
                self.count += 1
                remaining = int(self.account.posted_balance)

            emit(self.env, "TPM1", "transaction", {"remaining": int(remaining), "count": int(self.count)})


# ----------------------------
# Main
# ----------------------------

def read_requests_from_stdin(logger: logging.Logger) -> list[Request]:
    requests: list[Request] = []
    seq = 0
    for line in sys.stdin:
        s = line.strip()
        if not s:
            continue
        # Allow trailing comments with '#'
        if "#" in s:
            s = s.split("#", 1)[0].strip()
            if not s:
                continue

        parts = s.split()
        if len(parts) != 3:
            logger.warning("Skipping invalid input line (expected 3 fields): %r", line.rstrip("\n"))
            continue

        ts, valid_s, invalid_s = parts
        try:
            t = parse_timestamp_to_seconds(ts)
            valid = int(valid_s)
            invalid = int(invalid_s)
        except Exception as e:
            logger.warning("Skipping invalid input line %r: %s", line.rstrip("\n"), e)
            continue

        requests.append(Request(seq=seq, t=float(t), valid=valid, invalid=invalid))
        seq += 1

    # Preserve input order for same timestamps; ensure monotonic processing in reader by sorting by time then seq.
    requests.sort(key=lambda r: (r.t, r.seq))
    return requests


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="IOBS (Internet Online Banking System) DES Simulation")
    parser.add_argument("--simulation_time", type=float, default=1000000.0, help="Total simulation time in seconds.")
    args = parser.parse_args(argv)

    logger = setup_logging()

    # Seed randomness from system time (simulation must not use real-time delays).
    random.seed(time.time_ns())

    requests = read_requests_from_stdin(logger)

    env = simpy.Environment()

    # Stores (queues) between stages
    s_input_to_aam = simpy.Store(env)
    s_aam_to_anv = simpy.Store(env)
    s_anv_to_pv = simpy.Store(env)
    s_pv_to_bpm = simpy.Store(env)
    s_bpm_to_tpm = simpy.Store(env)

    # Shared account state (used to cap bills and compute remaining)
    account = AccountState(posted_balance=3000, available_balance=3000)
    account_lock = simpy.Resource(env, capacity=1)

    # Instantiate models
    input_reader = InputReader1(env, s_input_to_aam, requests, logger)
    aam = AAM1(env, s_input_to_aam, s_aam_to_anv)
    anv = ANV1(env, s_aam_to_anv, s_anv_to_pv)
    pv = PV1(env, s_anv_to_pv, s_pv_to_bpm)
    bpm = BPM1(env, s_pv_to_bpm, s_bpm_to_tpm, account, account_lock)
    tpm = TPM1(env, s_bpm_to_tpm, account, account_lock)

    # Start processes
    env.process(input_reader.run())
    env.process(aam.run())
    env.process(anv.run())
    env.process(pv.run())
    env.process(bpm.run())
    env.process(tpm.run())

    # Run simulation (fast, discrete-event)
    sim_end = float(args.simulation_time)
    if sim_end < 0:
        sim_end = 0.0

    env.run(until=sim_end)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))