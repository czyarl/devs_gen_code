#!/usr/bin/env python3
"""Internet Online Banking System (IOBS) - Discrete Event Simulation.

Entry point required by the assignment: `python run.py`.

The simulation reads timestamped requests from stdin and emits JSONL events to stdout.
All non-JSON output must go to stderr.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import random
import sys
import time
from dataclasses import dataclass
from typing import Iterable, Optional

import simpy


LOG = logging.getLogger(__name__)


PROCESSING_DELAY = 10.0  # seconds per entity


def _seed_random() -> None:
    # Requirement: use system time for seeds.
    random.seed(time.time_ns())


def _emit(time_value: float, model: str, event: str, data: dict) -> None:
    """Emit a single JSONL record to stdout."""
    sys.stdout.write(
        json.dumps({"time": float(time_value), "model": model, "event": event, "data": data})
        + "\n"
    )


def _parse_timestamp_to_seconds(ts: str) -> float:
    """Parse HH:MM:SS:mmm into seconds (float)."""
    parts = ts.split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid timestamp format: {ts!r}")
    hh, mm, ss, mmm = (int(p) for p in parts)
    return hh * 3600.0 + mm * 60.0 + ss + mmm / 1000.0


@dataclass(frozen=True)
class Request:
    order: int
    t: float
    valid: int
    invalid: int


def _read_requests(stdin: Iterable[str]) -> list[Request]:
    requests: list[Request] = []
    order = 0
    for raw_line in stdin:
        line = raw_line.strip()
        if not line:
            continue
        # Allow comments after '#'
        if "#" in line:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
        fields = line.split()
        if len(fields) < 3:
            raise ValueError(f"Invalid input line: {raw_line!r}")
        ts, valid_s, invalid_s = fields[0], fields[1], fields[2]
        req = Request(
            order=order,
            t=_parse_timestamp_to_seconds(ts),
            valid=int(valid_s),
            invalid=int(invalid_s),
        )
        requests.append(req)
        order += 1
    return requests


def _geometric_attempts(p_success: float = 0.5) -> int:
    """Sample attempts for geometric distribution (>=1) without looping."""
    # Inversion method for geometric distribution.
    u = random.random()
    if u <= 0.0:
        u = 1e-12
    return int(math.floor(math.log(u) / math.log(1.0 - p_success)) + 1)


class IOBSSim:
    def __init__(self, env: simpy.Environment):
        self.env = env
        # Single-server resources per entity to ensure sequential processing within each entity.
        self.aam = simpy.Resource(env, capacity=1)
        self.anv = simpy.Resource(env, capacity=1)
        self.pv = simpy.Resource(env, capacity=1)
        self.bpm = simpy.Resource(env, capacity=1)
        self.tpm = simpy.Resource(env, capacity=1)

        # Shared account state.
        # - committed_balance: balance after completed TPM transactions.
        # - pending_total: sum of amounts already billed by BPM but not yet completed by TPM.
        # This prevents BPM from generating bills that would overdraw the account when many
        # requests are in flight concurrently.
        self.state = {"committed_balance": 3000, "pending_total": 0, "count": 0}
        self.account_lock = simpy.Resource(env, capacity=1)

    def start(self) -> None:
        _emit(0.0, "input_reader1", "start", {})

    def process_request(self, req: Request):
        # Wait until the request timestamp (input event time).
        yield self.env.timeout(max(0.0, req.t - self.env.now))

        _emit(self.env.now, "input_reader1", "input", {"valid": req.valid, "invalid": req.invalid})

        # AAM stage
        with self.aam.request() as r:
            yield r
            yield self.env.timeout(PROCESSING_DELAY)
            if req.invalid == 1:
                _emit(self.env.now, "AAM1", "logout", {})
                return
            _emit(self.env.now, "AAM1", "account_generated", {})

        # ANV stage
        with self.anv.request() as r:
            yield r
            yield self.env.timeout(PROCESSING_DELAY)
            passed = 1 if random.random() < 0.5 else 0
            failed = 1 - passed
            _emit(self.env.now, "ANV1", "verification", {"pass": passed, "fail": failed})
            if failed:
                return

        # PV stage
        with self.pv.request() as r:
            yield r
            yield self.env.timeout(PROCESSING_DELAY)
            attempts = _geometric_attempts(0.5)
            _emit(self.env.now, "PV1", "verification", {"success": 1, "attempts": int(attempts)})

        # BPM stage
        # Generate bill amount (0-40) but ensure it does not exceed remaining balance
        # considering other in-flight bills.
        with self.bpm.request() as r:
            yield r
            yield self.env.timeout(PROCESSING_DELAY)
            with self.account_lock.request() as a:
                yield a
                available = int(self.state["committed_balance"]) - int(self.state["pending_total"])
                limit = min(40, max(0, available))
                amount = random.randint(0, limit) if limit > 0 else 0
                # reserve this amount until TPM completes
                self.state["pending_total"] = int(self.state["pending_total"]) + int(amount)
            _emit(self.env.now, "BPM1", "bill", {"amount": int(amount)})

        # TPM stage
        with self.tpm.request() as r:
            yield r
            yield self.env.timeout(PROCESSING_DELAY)
            with self.account_lock.request() as a:
                yield a
                self.state["committed_balance"] = int(self.state["committed_balance"]) - int(amount)
                self.state["pending_total"] = int(self.state["pending_total"]) - int(amount)
                self.state["count"] = int(self.state["count"]) + 1
                remaining = int(self.state["committed_balance"])
                count = int(self.state["count"])
            _emit(
                self.env.now,
                "TPM1",
                "transaction",
                {"remaining": int(remaining), "count": int(count)},
            )


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="IOBS discrete event simulation")
    p.add_argument(
        "--simulation_time",
        type=float,
        default=1000000.0,
        help="Total simulation time (seconds). Default: 1000000.0",
    )
    return p


def main(argv: Optional[list[str]] = None) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING)
    _seed_random()

    args = build_arg_parser().parse_args(argv)

    try:
        requests = _read_requests(sys.stdin)
    except Exception as e:
        # Any errors should not pollute stdout.
        LOG.exception("Failed to read input: %s", e)
        return 2

    env = simpy.Environment()
    sim = IOBSSim(env)
    sim.start()

    for req in requests:
        env.process(sim.process_request(req))

    # simpy requires `until` to be strictly greater than current time.
    until = float(args.simulation_time)
    if until > env.now:
        try:
            env.run(until=until)
        except Exception as e:
            LOG.exception("Simulation error: %s", e)
            return 3

    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
