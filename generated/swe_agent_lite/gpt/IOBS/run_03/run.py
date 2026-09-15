#!/usr/bin/env python3
"""Discrete Event Simulation: Internet Online Banking System (IOBS)

Entry point: python run.py

- Reads timestamped requests from stdin.
- Simulates a pipeline of entities with fixed processing delays using simpy.
- Emits required JSONL events to stdout only.
- Logs any debug info to stderr.

"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import simpy


PROCESSING_DELAY = 10.0  # seconds per entity


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )


def seed_rng() -> None:
    # Use system time for seed as required.
    ns = time.time_ns()
    random.seed(ns)


def emit(time_value: float, model: str, event: str, data: Dict) -> None:
    """Emit a single JSONL event to stdout."""
    obj = {"time": float(time_value), "model": model, "event": event, "data": data}
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def parse_timestamp_to_seconds(ts: str) -> float:
    """Parse HH:MM:SS:mmm into seconds as float."""
    parts = ts.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid timestamp format: {ts!r}")
    hh, mm, ss, mmm = parts
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(mmm) / 1000.0


@dataclass(frozen=True)
class Request:
    t: float
    valid: int
    invalid: int


class TPMState:
    def __init__(self, initial_balance: int = 3000):
        self.balance = int(initial_balance)
        self.count = 0


def input_reader1(env: simpy.Environment, requests: List[Request], out_store: simpy.Store):
    emit(0.0, "input_reader1", "start", {})

    # Ensure chronological processing; stable sort keeps input order for ties.
    requests_sorted = sorted(requests, key=lambda r: r.t)

    for req in requests_sorted:
        # Wait until request timestamp.
        if req.t > env.now:
            yield env.timeout(req.t - env.now)
        # Trigger input event at the request time.
        emit(env.now, "input_reader1", "input", {"valid": int(req.valid), "invalid": int(req.invalid)})
        yield out_store.put(req)


def aam1(env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store):
    while True:
        req: Request = yield in_store.get()
        # Processing delay
        yield env.timeout(PROCESSING_DELAY)
        if int(req.valid) == 1 and int(req.invalid) == 0:
            emit(env.now, "AAM1", "account_generated", {})
            yield out_store.put(req)
        else:
            # invalid login triggers logout and ends processing for this request
            emit(env.now, "AAM1", "logout", {})


def anv1(env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store):
    while True:
        req: Request = yield in_store.get()
        yield env.timeout(PROCESSING_DELAY)
        passed = 1 if random.random() < 0.5 else 0
        failed = 1 - passed
        emit(env.now, "ANV1", "verification", {"pass": passed, "fail": failed})
        if passed:
            yield out_store.put(req)
        # else: end processing


def pv1(env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store):
    while True:
        req: Request = yield in_store.get()
        yield env.timeout(PROCESSING_DELAY)
        attempts = 0
        # 50% chance success per attempt; keep trying until success.
        while True:
            attempts += 1
            if random.random() < 0.5:
                break
        emit(env.now, "PV1", "verification", {"success": 1, "attempts": int(attempts)})
        yield out_store.put(req)


def bpm1(env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store, tpm_state: TPMState):
    while True:
        req: Request = yield in_store.get()
        yield env.timeout(PROCESSING_DELAY)
        # Generate random bill amount between 0 and 40, constrained by remaining balance.
        max_amount = min(40, max(0, int(tpm_state.balance)))
        amount = random.randint(0, max_amount) if max_amount > 0 else 0
        emit(env.now, "BPM1", "bill", {"amount": int(amount)})
        yield out_store.put((req, int(amount)))


def tpm1(env: simpy.Environment, in_store: simpy.Store, tpm_state: TPMState):
    while True:
        _req, amount = yield in_store.get()
        yield env.timeout(PROCESSING_DELAY)
        amount_i = int(amount)
        if amount_i > tpm_state.balance:
            # Should not happen due to BPM constraint, but guard anyway.
            amount_i = tpm_state.balance
        tpm_state.balance -= amount_i
        tpm_state.count += 1
        emit(env.now, "TPM1", "transaction", {"remaining": int(tpm_state.balance), "count": int(tpm_state.count)})


def read_requests_from_stdin(stdin: Iterable[str]) -> List[Request]:
    requests: List[Request] = []
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        # Allow comments after '#'
        if "#" in line:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"Invalid input line (expected 3 fields): {line!r}")
        ts_s, valid_s, invalid_s = parts
        t = parse_timestamp_to_seconds(ts_s)
        requests.append(Request(t=t, valid=int(valid_s), invalid=int(invalid_s)))
    return requests


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="DES simulation for IOBS")
    p.add_argument(
        "--simulation_time",
        type=float,
        default=1000000.0,
        help="Total simulation time in seconds (default: 1000000.0)",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    setup_logging()
    seed_rng()

    args = build_arg_parser().parse_args(argv)

    try:
        requests = read_requests_from_stdin(sys.stdin)
    except Exception as e:
        logging.error("Failed to read stdin: %s", e)
        return 2

    env = simpy.Environment()

    # Stores between pipeline stages
    s_in_aam = simpy.Store(env)
    s_aam_anv = simpy.Store(env)
    s_anv_pv = simpy.Store(env)
    s_pv_bpm = simpy.Store(env)
    s_bpm_tpm = simpy.Store(env)

    tpm_state = TPMState(initial_balance=3000)

    env.process(input_reader1(env, requests, s_in_aam))
    env.process(aam1(env, s_in_aam, s_aam_anv))
    env.process(anv1(env, s_aam_anv, s_anv_pv))
    env.process(pv1(env, s_anv_pv, s_pv_bpm))
    env.process(bpm1(env, s_pv_bpm, s_bpm_tpm, tpm_state))
    env.process(tpm1(env, s_bpm_tpm, tpm_state))

    # Run until simulation_time; simpy uses simulation time (not real time).
    # This will complete quickly in real time for typical input sizes.
    env.run(until=float(args.simulation_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
