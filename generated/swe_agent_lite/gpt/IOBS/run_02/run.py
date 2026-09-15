#!/usr/bin/env python3
"""Discrete Event Simulation: Internet Online Banking System (IOBS)

Entry point: python run.py

- Reads timestamped requests from stdin.
- Simulates a pipeline of entities with fixed processing delays using SimPy.
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
    # Use system time as requested.
    ns = time.time_ns()
    random.seed(ns)


def emit(time_value: float, model: str, event: str, data: dict) -> None:
    """Emit a single JSONL event to stdout."""
    sys.stdout.write(json.dumps({"time": float(time_value), "model": model, "event": event, "data": data}) + "\n")


def parse_timestamp_to_seconds(ts: str) -> float:
    """Parse HH:MM:SS:mmm into seconds as float."""
    try:
        hh, mm, ss, mmm = ts.strip().split(":")
        return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(mmm) / 1000.0
    except Exception as e:
        raise ValueError(f"Invalid timestamp '{ts}': expected HH:MM:SS:mmm") from e


def parse_input_line(line: str) -> Optional[Tuple[float, int, int]]:
    """Parse one stdin line. Returns (time, valid, invalid) or None for blank/comment."""
    raw = line.strip()
    if not raw:
        return None
    # allow inline comments starting with '#'
    if "#" in raw:
        raw = raw.split("#", 1)[0].strip()
        if not raw:
            return None
    parts = raw.split()
    if len(parts) != 3:
        raise ValueError(f"Invalid input line (expected 3 fields): {line.rstrip()}")
    t = parse_timestamp_to_seconds(parts[0])
    valid = int(parts[1])
    invalid = int(parts[2])
    return t, valid, invalid


@dataclass
class Request:
    valid: int
    invalid: int


class TPM:
    def __init__(self, env: simpy.Environment):
        self.env = env
        self.balance = 3000
        self.count = 0

    def process(self, amount: int) -> None:
        # Apply transaction
        self.balance -= amount
        self.count += 1
        emit(self.env.now, "TPM1", "transaction", {"remaining": int(self.balance), "count": int(self.count)})


class IOBS:
    def __init__(self, env: simpy.Environment):
        self.env = env
        self.tpm = TPM(env)

    def handle_request(self, req: Request) -> simpy.events.Event:
        """Full pipeline for a single request."""
        return self.env.process(self._pipeline(req))

    def _pipeline(self, req: Request):
        # AAM
        yield self.env.timeout(PROCESSING_DELAY)
        if req.valid == 1 and req.invalid == 0:
            emit(self.env.now, "AAM1", "account_generated", {})
        else:
            # invalid login triggers logout and ends processing
            emit(self.env.now, "AAM1", "logout", {})
            return

        # ANV
        yield self.env.timeout(PROCESSING_DELAY)
        passed = 1 if random.random() < 0.5 else 0
        failed = 1 - passed
        emit(self.env.now, "ANV1", "verification", {"pass": int(passed), "fail": int(failed)})
        if failed:
            return

        # PV (keeps trying until success)
        yield self.env.timeout(PROCESSING_DELAY)
        attempts = 0
        while True:
            attempts += 1
            if random.random() < 0.5:
                break
        emit(self.env.now, "PV1", "verification", {"success": 1, "attempts": int(attempts)})

        # BPM
        yield self.env.timeout(PROCESSING_DELAY)
        max_amount = min(40, self.tpm.balance)
        amount = random.randint(0, int(max_amount)) if max_amount > 0 else 0
        emit(self.env.now, "BPM1", "bill", {"amount": int(amount)})

        # TPM
        yield self.env.timeout(PROCESSING_DELAY)
        self.tpm.process(int(amount))


def input_reader(env: simpy.Environment, system: IOBS, simulation_time: float) -> simpy.events.Event:
    """Reads stdin lines, schedules request arrivals, and emits input_reader1 events."""
    emit(0.0, "input_reader1", "start", {})

    for line in sys.stdin:
        parsed = parse_input_line(line)
        if parsed is None:
            continue
        t, valid, invalid = parsed
        if t > simulation_time:
            # Ignore arrivals beyond simulation horizon
            continue

        # Wait until the request timestamp (simulation time)
        # If multiple requests have close timestamps, this preserves ordering.
        if t < env.now:
            # If input is not sorted, schedule immediately at current time.
            logging.warning("Input timestamp %.3f is earlier than current simulation time %.3f; scheduling immediately.", t, env.now)
            t = env.now
        yield env.timeout(t - env.now)

        emit(env.now, "input_reader1", "input", {"valid": int(valid), "invalid": int(invalid)})
        system.handle_request(Request(valid=int(valid), invalid=int(invalid)))

    # No more input; reader ends.


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="IOBS discrete event simulation")
    p.add_argument("--simulation_time", type=float, default=1000000.0, help="Total simulation time in seconds")
    return p


def main(argv: Optional[list[str]] = None) -> int:
    setup_logging()
    seed_rng()

    args = build_arg_parser().parse_args(argv)

    env = simpy.Environment()
    system = IOBS(env)

    env.process(input_reader(env, system, float(args.simulation_time)))

    # Run until simulation_time; SimPy will stop even if there are pending events beyond.
    env.run(until=float(args.simulation_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
