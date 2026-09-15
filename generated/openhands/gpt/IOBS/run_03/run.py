#!/usr/bin/env python3
"""Internet Online Banking System (IOBS) - Discrete Event Simulation

Entry point: python run.py

All simulation events are emitted as JSONL to stdout.
All logs/debug info go to stderr.

Implements the pipeline:
Input → AAM → ANV → PV → BPM → TPM → Output
"""

import argparse
import json
import logging
import random
import sys
import time
from collections import namedtuple

import simpy


PROCESSING_DELAY = 10.0  # seconds per entity


def parse_timestamp_to_seconds(ts: str) -> float:
    """Parse HH:MM:SS:mmm into seconds (float)."""
    parts = ts.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid timestamp format: {ts!r}")
    hh, mm, ss, mmm = parts
    h = int(hh)
    m = int(mm)
    s = int(ss)
    ms = int(mmm)
    return h * 3600.0 + m * 60.0 + s + ms / 1000.0


def emit(time_value: float, model: str, event: str, data: dict) -> None:
    """Emit a single JSONL event to stdout."""
    sys.stdout.write(
        json.dumps({"time": float(time_value), "model": model, "event": event, "data": data})
        + "\n"
    )


# Use only stdlib collections (namedtuple) rather than dataclasses/typing.
Request = namedtuple("Request", ["seq", "t_in", "valid", "invalid"])


class AccountState:
    def __init__(self, balance: int = 3000, count: int = 0):
        self.balance = int(balance)
        self.count = int(count)


class IOBSSim:
    def __init__(self, env: simpy.Environment, account: AccountState):
        self.env = env
        self.account = account

        # Single-server (sequential) resources per entity.
        self.aam_res = simpy.Resource(env, capacity=1)
        self.anv_res = simpy.Resource(env, capacity=1)
        self.pv_res = simpy.Resource(env, capacity=1)

        # Serialize bill generation + transaction processing to ensure
        # BPM never generates an amount exceeding the *current* remaining balance.
        self.bpm_tpm_res = simpy.Resource(env, capacity=1)

    def start(self) -> None:
        emit(0.0, "input_reader1", "start", {})

    def schedule_input(self, req: Request) -> None:
        self.env.process(self._input_process(req))

    def _input_process(self, req: Request):
        # Wait until the input timestamp.
        if req.t_in < 0:
            return
        yield self.env.timeout(req.t_in)
        emit(self.env.now, "input_reader1", "input", {"valid": int(req.valid), "invalid": int(req.invalid)})
        # Forward to AAM.
        self.env.process(self._aam(req))

    def _aam(self, req: Request):
        with self.aam_res.request() as token:
            yield token
            yield self.env.timeout(PROCESSING_DELAY)
            # valid is always 1 per scenario; invalid determines logout.
            if int(req.valid) == 1 and int(req.invalid) == 0:
                emit(self.env.now, "AAM1", "account_generated", {})
                self.env.process(self._anv(req))
            else:
                emit(self.env.now, "AAM1", "logout", {})

    def _anv(self, req: Request):
        with self.anv_res.request() as token:
            yield token
            yield self.env.timeout(PROCESSING_DELAY)
            passed = 1 if random.random() < 0.5 else 0
            failed = 1 - passed
            emit(self.env.now, "ANV1", "verification", {"pass": passed, "fail": failed})
            if passed:
                self.env.process(self._pv(req))

    def _pv(self, req: Request):
        with self.pv_res.request() as token:
            yield token
            yield self.env.timeout(PROCESSING_DELAY)
            # Geometric(p=0.5) attempts, always eventually succeeds.
            attempts = 1
            while True:
                if random.random() < 0.5:
                    break
                attempts += 1
                # Safety cap to guarantee termination even if RNG misbehaves.
                if attempts >= 10_000:
                    break
            emit(self.env.now, "PV1", "verification", {"success": 1, "attempts": int(attempts)})
            self.env.process(self._bpm_tpm(req))

    def _bpm_tpm(self, req: Request):
        # Serialize BPM+TPM around the shared account balance.
        with self.bpm_tpm_res.request() as token:
            yield token

            # BPM delay + bill generation.
            yield self.env.timeout(PROCESSING_DELAY)
            max_amount = min(40, max(0, int(self.account.balance)))
            amount = random.randint(0, max_amount) if max_amount > 0 else 0
            emit(self.env.now, "BPM1", "bill", {"amount": int(amount)})

            # TPM delay + transaction processing.
            yield self.env.timeout(PROCESSING_DELAY)
            self.account.balance = int(self.account.balance) - int(amount)
            if self.account.balance < 0:
                # Should not happen due to serialization and max_amount logic.
                self.account.balance = 0
            self.account.count += 1
            emit(
                self.env.now,
                "TPM1",
                "transaction",
                {"remaining": int(self.account.balance), "count": int(self.account.count)},
            )


def read_requests_from_stdin():
    reqs = []
    seq = 0
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        # Allow comments after '#'
        if "#" in line:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
        parts = line.split()
        if len(parts) < 3:
            raise ValueError(f"Invalid input line: {raw!r}")
        ts, valid_s, invalid_s = parts[0], parts[1], parts[2]
        t_in = parse_timestamp_to_seconds(ts)
        valid = int(valid_s)
        invalid = int(invalid_s)
        reqs.append(Request(seq=seq, t_in=t_in, valid=valid, invalid=invalid))
        seq += 1
    return reqs


def run_env_with_watchdog(env: simpy.Environment, until: float, wall_clock_budget_s: float = 9.5) -> None:
    """Run simpy environment step-by-step to guarantee real-time termination.

    Processes all events with timestamp <= until.
    """
    start = time.monotonic()

    while True:
        if time.monotonic() - start > wall_clock_budget_s:
            logging.warning(
                "Wall-clock budget exceeded; stopping simulation early at sim_time=%.3f", float(env.now)
            )
            break

        nxt = env.peek()

        # No more scheduled events.
        if nxt == float("inf"):
            break

        # Stop if the next event is beyond the requested until time.
        if nxt > until:
            break

        # Step the simulation by one event.
        env.step()


def main(argv) -> int:
    parser = argparse.ArgumentParser(description="IOBS discrete event simulation")
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=1000000.0,
        help="Total simulation time in seconds (default: 1000000.0)",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.WARNING, stream=sys.stderr, format="[%(levelname)s] %(message)s")

    # Seed RNG from system time.
    random.seed(time.time_ns())

    try:
        requests = read_requests_from_stdin()
    except Exception as e:
        logging.error("Failed to read/parse stdin: %s", e)
        return 2

    env = simpy.Environment(initial_time=0.0)
    account = AccountState(balance=3000, count=0)
    sim = IOBSSim(env, account)

    # Emit start event at t=0.
    sim.start()

    # Schedule inputs in stdin order (important for identical timestamps).
    for req in requests:
        sim.schedule_input(req)

    # Run the simulation with a real-time watchdog.
    sim_until = float(args.simulation_time)
    if sim_until < 0:
        sim_until = 0.0

    run_env_with_watchdog(env, until=sim_until, wall_clock_budget_s=9.5)

    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
