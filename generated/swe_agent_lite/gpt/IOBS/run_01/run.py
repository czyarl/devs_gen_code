#!/usr/bin/env python3
"""Discrete Event Simulation: Internet Online Banking System (IOBS)

Entry point: python run.py

- Reads timestamped requests from stdin.
- Simulates a pipeline of entities with fixed processing delays using simpy.
- Emits required JSONL events to stdout only.
- Logs debug information to stderr.

The simulation is designed to finish quickly in real time (no wall-clock sleeps).
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from dataclasses import dataclass
from typing import Optional, Tuple

import simpy


PROCESSING_DELAY = 10.0  # seconds per entity


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )


def seed_rng() -> None:
    # Use system time as required.
    seed = time.time_ns()
    random.seed(seed)


def emit(time_value: float, model: str, event: str, data: dict) -> None:
    """Emit a single JSONL event to stdout."""
    obj = {"time": float(time_value), "model": model, "event": event, "data": data}
    sys.stdout.write(json.dumps(obj) + "\n")


def parse_timestamp_to_seconds(ts: str) -> float:
    """Parse HH:MM:SS:mmm into seconds as float."""
    parts = ts.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid timestamp format: {ts!r}")
    hh, mm, ss, mmm = parts
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(mmm) / 1000.0


@dataclass
class Request:
    t_in: float
    valid: int
    invalid: int


class TPMState:
    def __init__(self, initial_balance: int = 3000):
        self.balance = int(initial_balance)
        self.count = 0


def input_reader1(env: simpy.Environment, out_store: simpy.Store, requests: list[Request]) -> simpy.events.Event:
    emit(0.0, "input_reader1", "start", {})

    # Requests may have close timestamps; schedule each at its own time.
    for req in requests:
        # Wait until request timestamp.
        if req.t_in < env.now:
            # If input is not sorted, still handle by emitting immediately.
            logging.warning("Request timestamp %.3f < current time %.3f; emitting immediately", req.t_in, env.now)
            yield env.timeout(0)
        else:
            yield env.timeout(req.t_in - env.now)

        emit(env.now, "input_reader1", "input", {"valid": req.valid, "invalid": req.invalid})
        yield out_store.put(req)


def AAM1(env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store) -> simpy.events.Event:
    while True:
        req: Request = yield in_store.get()
        yield env.timeout(PROCESSING_DELAY)

        # valid is always 1 for compatibility; invalid determines logout.
        if req.valid == 1 and req.invalid == 0:
            emit(env.now, "AAM1", "account_generated", {})
            yield out_store.put(req)
        else:
            emit(env.now, "AAM1", "logout", {})
            # End processing for this request.


def ANV1(env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store) -> simpy.events.Event:
    while True:
        req: Request = yield in_store.get()
        yield env.timeout(PROCESSING_DELAY)

        passed = 1 if random.random() < 0.5 else 0
        failed = 1 - passed
        emit(env.now, "ANV1", "verification", {"pass": passed, "fail": failed})

        if passed:
            yield out_store.put(req)
        # else: end processing


def PV1(env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store) -> simpy.events.Event:
    while True:
        req: Request = yield in_store.get()
        yield env.timeout(PROCESSING_DELAY)

        attempts = 0
        while True:
            attempts += 1
            if random.random() < 0.5:
                break
        emit(env.now, "PV1", "verification", {"success": 1, "attempts": attempts})
        yield out_store.put(req)


def BPM1(env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store, tpm_state: TPMState) -> simpy.events.Event:
    while True:
        req: Request = yield in_store.get()
        yield env.timeout(PROCESSING_DELAY)

        # Generate random bill amount 0..40 but not exceeding remaining balance.
        max_amount = min(40, max(0, tpm_state.balance))
        amount = random.randint(0, max_amount) if max_amount > 0 else 0
        emit(env.now, "BPM1", "bill", {"amount": int(amount)})
        yield out_store.put((req, int(amount)))


def TPM1(env: simpy.Environment, in_store: simpy.Store, tpm_state: TPMState) -> simpy.events.Event:
    while True:
        req_amount: Tuple[Request, int] = yield in_store.get()
        _req, amount = req_amount
        yield env.timeout(PROCESSING_DELAY)

        tpm_state.balance -= int(amount)
        tpm_state.count += 1
        emit(env.now, "TPM1", "transaction", {"remaining": int(tpm_state.balance), "count": int(tpm_state.count)})


def read_requests_from_stdin() -> list[Request]:
    requests: list[Request] = []
    for line in sys.stdin:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Allow inline comments after data.
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        parts = line.split()
        if len(parts) < 3:
            raise ValueError(f"Invalid input line: {line!r}")
        ts, valid_s, invalid_s = parts[0], parts[1], parts[2]
        t_in = parse_timestamp_to_seconds(ts)
        requests.append(Request(t_in=t_in, valid=int(valid_s), invalid=int(invalid_s)))

    # Sort by timestamp to ensure correct scheduling when inputs are out of order.
    requests.sort(key=lambda r: r.t_in)
    return requests


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="IOBS DES simulation")
    p.add_argument("--simulation_time", type=float, default=1000000.0, help="Total simulation time in seconds")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    setup_logging()
    seed_rng()

    args = build_arg_parser().parse_args(argv)

    try:
        requests = read_requests_from_stdin()
    except Exception as e:
        logging.error("Failed to read requests: %s", e)
        return 2

    env = simpy.Environment()

    s_aam = simpy.Store(env)
    s_anv = simpy.Store(env)
    s_pv = simpy.Store(env)
    s_bpm = simpy.Store(env)
    s_tpm = simpy.Store(env)

    tpm_state = TPMState(initial_balance=3000)

    env.process(input_reader1(env, s_aam, requests))
    env.process(AAM1(env, s_aam, s_anv))
    env.process(ANV1(env, s_anv, s_pv))
    env.process(PV1(env, s_pv, s_bpm))
    env.process(BPM1(env, s_bpm, s_tpm, tpm_state))
    env.process(TPM1(env, s_tpm, tpm_state))

    # Run until simulation_time or until no more events.
    # simpy will stop when there are no scheduled events; however, our worker
    # processes wait on stores forever. So we run until simulation_time.
    env.run(until=float(args.simulation_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
