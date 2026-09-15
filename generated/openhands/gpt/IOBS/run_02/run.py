#!/usr/bin/env python3
"""Internet Online Banking System (IOBS) discrete-event simulation.

Entry point: python run.py

Stdout: JSONL events only.
Stderr: logs/debug.
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
WALLCLOCK_BUDGET_S = 9.8  # hard-stop to guarantee exit within ~10s


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s:%(name)s:%(message)s",
        stream=sys.stderr,
    )


def _seed_random() -> None:
    # Requirement: use system time to set seed for random number generation.
    ns = time.time_ns()
    random.seed(ns)


def _parse_timestamp_to_seconds(ts: str) -> float:
    """Parse HH:MM:SS:mmm into seconds (float)."""
    parts = ts.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid timestamp format: {ts!r}")
    hh, mm, ss, mmm = (int(p) for p in parts)
    return hh * 3600.0 + mm * 60.0 + ss + (mmm / 1000.0)


def _emit(time_value: float, model: str, event: str, data: Dict[str, Any]) -> None:
    obj = {"time": float(time_value), "model": model, "event": event, "data": data}
    sys.stdout.write(json.dumps(obj) + "\n")


@dataclass(frozen=True)
class Request:
    idx: int
    t_arrival: float
    valid: int
    invalid: int


class BalanceLedger:
    """Tracks actual balance and reservations to enforce non-negative bills."""

    def __init__(self, env: simpy.Environment, initial_balance: int = 3000):
        self.env = env
        self._lock = simpy.Resource(env, capacity=1)
        self.balance: int = int(initial_balance)
        self.reserved: int = 0
        self.tx_count: int = 0

    @property
    def available(self) -> int:
        return self.balance - self.reserved

    def lock(self):
        return self._lock.request()


def process_request(env: simpy.Environment, req: Request, ledger: BalanceLedger):
    """A single request moving through the pipeline."""

    # input_reader1: input event at its timestamp.
    if req.t_arrival > env.now:
        yield env.timeout(req.t_arrival - env.now)
    _emit(env.now, "input_reader1", "input", {"valid": int(req.valid), "invalid": int(req.invalid)})

    # AAM
    yield env.timeout(PROCESSING_DELAY)
    if int(req.invalid) == 1:
        _emit(env.now, "AAM1", "logout", {})
        return
    _emit(env.now, "AAM1", "account_generated", {})

    # ANV (50% pass)
    yield env.timeout(PROCESSING_DELAY)
    passed = 1 if random.random() < 0.5 else 0
    failed = 1 - passed
    _emit(env.now, "ANV1", "verification", {"pass": int(passed), "fail": int(failed)})
    if failed:
        return

    # PV (keep trying until success; always success)
    yield env.timeout(PROCESSING_DELAY)
    attempts = 0
    while True:
        attempts += 1
        if random.random() < 0.5:
            break
    _emit(env.now, "PV1", "verification", {"success": 1, "attempts": int(attempts)})

    # BPM: generate bill amount 0-40, constrained by remaining available balance.
    yield env.timeout(PROCESSING_DELAY)
    with ledger.lock() as lock_req:
        yield lock_req
        max_amt = max(0, min(40, int(ledger.available)))
        amount = random.randint(0, max_amt)
        ledger.reserved += amount
    _emit(env.now, "BPM1", "bill", {"amount": int(amount)})

    # TPM: apply transaction to balance.
    yield env.timeout(PROCESSING_DELAY)
    with ledger.lock() as lock_req:
        yield lock_req
        # Safety: amount should never exceed balance due to reservation.
        if amount > ledger.balance:
            amount = ledger.balance
        ledger.balance -= amount
        ledger.reserved -= amount
        ledger.tx_count += 1
        remaining = ledger.balance
        count = ledger.tx_count

    _emit(env.now, "TPM1", "transaction", {"remaining": int(remaining), "count": int(count)})


def input_reader(env: simpy.Environment, requests: List[Request], ledger: BalanceLedger):
    """Starts the simulation and spawns request processes.

    Implemented as a SimPy process (generator) so it can be scheduled via env.process().
    """

    _emit(env.now, "input_reader1", "start", {})

    # Spawn request processes in timestamp order (stable by input index).
    for req in sorted(requests, key=lambda r: (r.t_arrival, r.idx)):
        env.process(process_request(env, req, ledger))

    # Yield once so this function is a generator for SimPy.
    yield env.timeout(0)


def _read_requests_from_stdin(logger: logging.Logger) -> List[Request]:
    requests: List[Request] = []
    idx = 0
    for raw in sys.stdin:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Allow inline comments after fields.
        tokens = line.split()
        if len(tokens) < 3:
            logger.warning("Skipping malformed line: %r", raw.rstrip("\n"))
            continue
        ts_s, valid_s, invalid_s = tokens[0], tokens[1], tokens[2]
        try:
            t = _parse_timestamp_to_seconds(ts_s)
            valid = int(valid_s)
            invalid = int(invalid_s)
        except Exception as e:
            logger.warning("Skipping line due to parse error (%s): %r", e, raw.rstrip("\n"))
            continue
        requests.append(Request(idx=idx, t_arrival=float(t), valid=valid, invalid=invalid))
        idx += 1
    return requests


def main(argv: Optional[List[str]] = None) -> int:
    _configure_logging()
    logger = logging.getLogger("iobs")

    parser = argparse.ArgumentParser(description="IOBS discrete-event simulation")
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=1_000_000.0,
        help="Total simulation time in seconds (default: 1000000.0)",
    )
    args = parser.parse_args(argv)

    _seed_random()

    requests = _read_requests_from_stdin(logger)

    env = simpy.Environment()
    ledger = BalanceLedger(env, initial_balance=3000)

    env.process(input_reader(env, requests, ledger))

    # Run until no events remain, but cap by --simulation_time and a computed end.
    if requests:
        latest_arrival = max(r.t_arrival for r in requests)
    else:
        latest_arrival = 0.0

    # Worst-case pipeline completion is arrival + 5 * 10s (AAM..TPM).
    computed_end = latest_arrival + 5.0 * PROCESSING_DELAY + 1e-9
    until_t = min(float(args.simulation_time), computed_end)

    # Guarantee program exits within ~10s wall-clock time.
    # SimPy uses simulation time; this guard only enforces runtime limits.
    t0 = time.time()
    while True:
        if (time.time() - t0) >= WALLCLOCK_BUDGET_S:
            logger.warning(
                "Wall-clock budget reached (%.2fs); stopping simulation early at t=%.3f",
                WALLCLOCK_BUDGET_S,
                env.now,
            )
            break

        next_t = env.peek()
        if next_t == float("inf"):
            # No more scheduled events.
            break
        if next_t > until_t:
            break

        # Advance exactly one scheduled event to guarantee progress even when
        # multiple events share the same timestamp.
        env.step()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
