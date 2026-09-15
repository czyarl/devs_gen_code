#!/usr/bin/env python3
"""IOBS - Internet Online Banking System discrete-event simulation.

Entry point: python run.py

Reads requests from stdin, simulates authentication and transaction pipeline,
prints JSONL events to stdout.

Output to stdout MUST be JSONL only.
All non-essential logs go to stderr.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import simpy


PROCESSING_DELAY = 10.0  # seconds per entity


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="[%(levelname)s] %(message)s",
    )


def _seed_rng() -> None:
    # Use system time (ns) for seed as requested.
    seed = time.time_ns()
    random.seed(seed)


def _parse_timestamp_to_seconds(ts: str) -> float:
    """Parse HH:MM:SS:mmm into seconds as float."""
    try:
        hh, mm, ss, mmm = ts.strip().split(":")
        return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(mmm) / 1000.0
    except Exception as e:  # pragma: no cover
        raise ValueError(f"Invalid timestamp '{ts}': expected HH:MM:SS:mmm") from e


def emit(time_value: float, model: str, event: str, data: Dict[str, Any]) -> None:
    """Emit a JSONL event to stdout."""
    obj = {"time": float(time_value), "model": model, "event": event, "data": data}
    sys.stdout.write(json.dumps(obj) + "\n")


@dataclass
class AccountState:
    balance: int = 3000
    reserved: int = 0
    tx_count: int = 0


@dataclass(frozen=True)
class Request:
    req_id: int
    time: float
    valid: int
    invalid: int


class IOBSModels:
    def __init__(self, env: simpy.Environment):
        self.env = env

        # Single-server resources per entity to enforce sequential processing per entity.
        self.aam_res = simpy.Resource(env, capacity=1)
        self.anv_res = simpy.Resource(env, capacity=1)
        self.pv_res = simpy.Resource(env, capacity=1)
        self.bpm_res = simpy.Resource(env, capacity=1)
        self.tpm_res = simpy.Resource(env, capacity=1)

        # Protect shared account state.
        self.account_lock = simpy.Resource(env, capacity=1)
        self.account = AccountState()

    def start_request_flow(self, req: Request) -> None:
        self.env.process(self._flow(req))

    def _flow(self, req: Request):
        # AAM1
        with self.aam_res.request() as r:
            yield r
            yield self.env.timeout(PROCESSING_DELAY)
            if req.invalid == 1:
                emit(self.env.now, "AAM1", "logout", {})
                return
            emit(self.env.now, "AAM1", "account_generated", {})

        # ANV1
        with self.anv_res.request() as r:
            yield r
            yield self.env.timeout(PROCESSING_DELAY)
            passed = 1 if random.random() < 0.5 else 0
            failed = 1 - passed
            emit(self.env.now, "ANV1", "verification", {"pass": passed, "fail": failed})
            if failed:
                return

        # PV1
        with self.pv_res.request() as r:
            yield r
            yield self.env.timeout(PROCESSING_DELAY)
            # Geometric number of attempts with p=0.5, always succeeds eventually.
            attempts = 1
            while random.random() >= 0.5:
                attempts += 1
            emit(self.env.now, "PV1", "verification", {"success": 1, "attempts": attempts})

        # BPM1
        with self.bpm_res.request() as r:
            yield r
            yield self.env.timeout(PROCESSING_DELAY)
            # Generate bill amount in [0, 40] constrained by available balance.
            with self.account_lock.request() as lk:
                yield lk
                available = max(0, self.account.balance - self.account.reserved)
                amount = random.randint(0, 40)
                if amount > available:
                    amount = available
                self.account.reserved += amount
            emit(self.env.now, "BPM1", "bill", {"amount": int(amount)})

        # TPM1
        with self.tpm_res.request() as r:
            yield r
            yield self.env.timeout(PROCESSING_DELAY)
            with self.account_lock.request() as lk:
                yield lk
                # Safety cap.
                if amount > self.account.balance:
                    amount = self.account.balance
                self.account.balance -= amount
                self.account.reserved -= amount
                self.account.tx_count += 1
                remaining = self.account.balance
                count = self.account.tx_count
            emit(self.env.now, "TPM1", "transaction", {"remaining": int(remaining), "count": int(count)})


def read_requests_from_stdin() -> List[Request]:
    reqs: List[Request] = []
    for idx, raw in enumerate(sys.stdin):
        line = raw.strip()
        if not line:
            continue
        # Allow trailing comments.
        if "#" in line:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
        parts = line.split()
        if len(parts) != 3:
            raise ValueError(f"Invalid input line: '{raw.rstrip()}'")
        ts_s = _parse_timestamp_to_seconds(parts[0])
        valid = int(parts[1])
        invalid = int(parts[2])
        reqs.append(Request(req_id=idx, time=ts_s, valid=valid, invalid=invalid))

    # Sort by time, preserve input order for same timestamp.
    reqs.sort(key=lambda r: (r.time, r.req_id))
    return reqs


def input_reader_process(env: simpy.Environment, models: IOBSModels, reqs: List[Request]):
    emit(0.0, "input_reader1", "start", {})
    for req in reqs:
        # Move simulation time to request timestamp.
        if req.time > env.now:
            yield env.timeout(req.time - env.now)
        emit(env.now, "input_reader1", "input", {"valid": int(req.valid), "invalid": int(req.invalid)})
        models.start_request_flow(req)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="IOBS discrete-event simulation")
    p.add_argument(
        "--simulation_time",
        type=float,
        default=1000000.0,
        help="Total simulation time in seconds.",
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    _setup_logging()
    _seed_rng()

    args = build_arg_parser().parse_args(argv)

    try:
        reqs = read_requests_from_stdin()
    except Exception as e:
        logging.error(str(e))
        return 2

    env = simpy.Environment()
    models = IOBSModels(env)

    env.process(input_reader_process(env, models, reqs))

    # Run simulation. Uses simulation time only; finishes quickly in real time.
    env.run(until=float(args.simulation_time))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
