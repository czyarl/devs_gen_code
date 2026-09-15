#!/usr/bin/env python3
import argparse
import sys
import json
import logging
import random
import time
from dataclasses import dataclass

import simpy

# Optional (requested in allowed libs list). Not required for runtime logic.
try:
    import xdevs  # noqa: F401
except Exception:
    xdevs = None  # type: ignore


PROCESSING_DELAY = 10.0


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("iobs_sim")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    formatter = logging.Formatter("[%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.handlers.clear()
    logger.addHandler(handler)
    return logger


def emit_event(sim_time: float, model: str, event: str, data: dict) -> None:
    obj = {"time": float(sim_time), "model": model, "event": event, "data": data}
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def parse_timestamp_to_seconds(ts: str) -> float:
    # Format: HH:MM:SS:mmm
    parts = ts.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid timestamp format: {ts!r}")
    hh, mm, ss, mmm = parts
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(mmm) / 1000.0


def read_requests_from_stdin(logger: logging.Logger):
    """
    Reads stdin line-by-line. Each non-empty line:
      HH:MM:SS:mmm valid invalid
    Supports inline comments starting with '#'.
    """
    reqs = []
    req_id = 0
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
        fields = line.split()
        if len(fields) != 3:
            logger.warning("Skipping invalid input line (expected 3 fields): %r", raw.rstrip("\n"))
            continue
        ts, valid_s, invalid_s = fields
        try:
            t = parse_timestamp_to_seconds(ts)
            valid = int(valid_s)
            invalid = int(invalid_s)
        except Exception as e:
            logger.warning("Skipping invalid input line %r due to parse error: %s", raw.rstrip("\n"), e)
            continue
        reqs.append((t, req_id, valid, invalid))
        req_id += 1

    # Sort by timestamp then input order to handle close timestamps correctly.
    reqs.sort(key=lambda x: (x[0], x[1]))
    return reqs


@dataclass
class BankState:
    env: simpy.Environment
    balance: int = 3000
    reserved: int = 0
    count: int = 0

    def __post_init__(self):
        self.lock = simpy.Resource(self.env, capacity=1)

    def available(self) -> int:
        return max(0, self.balance - self.reserved)


class InputReader:
    def __init__(self, env: simpy.Environment, out_store: simpy.Store, requests, logger: logging.Logger):
        self.env = env
        self.out = out_store
        self.requests = requests
        self.logger = logger
        self.model = "input_reader1"

    def run(self):
        emit_event(self.env.now, self.model, "start", {})
        last_t = 0.0
        for t, req_id, valid, invalid in self.requests:
            if t < last_t:
                # Should not happen due to sorting, but keep robust.
                t = last_t
            yield self.env.timeout(t - self.env.now)
            emit_event(self.env.now, self.model, "input", {"valid": int(valid), "invalid": int(invalid)})
            yield self.out.put({"id": req_id, "valid": int(valid), "invalid": int(invalid)})
            last_t = t


class AAM:
    def __init__(self, env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store, logger: logging.Logger):
        self.env = env
        self.inp = in_store
        self.out = out_store
        self.logger = logger
        self.model = "AAM1"

    def run(self):
        while True:
            msg = yield self.inp.get()
            # Processing delay
            yield self.env.timeout(PROCESSING_DELAY)
            if msg.get("valid", 1) == 1 and msg.get("invalid", 0) == 0:
                emit_event(self.env.now, self.model, "account_generated", {})
                yield self.out.put(msg)
            else:
                emit_event(self.env.now, self.model, "logout", {})
                # End processing for this request


class ANV:
    def __init__(self, env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store, logger: logging.Logger):
        self.env = env
        self.inp = in_store
        self.out = out_store
        self.logger = logger
        self.model = "ANV1"

    def run(self):
        while True:
            msg = yield self.inp.get()
            yield self.env.timeout(PROCESSING_DELAY)
            passed = 1 if random.random() < 0.5 else 0
            failed = 1 - passed
            emit_event(self.env.now, self.model, "verification", {"pass": passed, "fail": failed})
            if passed:
                yield self.out.put(msg)
            # else: end processing


class PV:
    def __init__(self, env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store, logger: logging.Logger):
        self.env = env
        self.inp = in_store
        self.out = out_store
        self.logger = logger
        self.model = "PV1"

    @staticmethod
    def geometric_attempts(p_success: float = 0.5) -> int:
        attempts = 1
        while random.random() >= p_success:
            attempts += 1
        return attempts

    def run(self):
        while True:
            msg = yield self.inp.get()
            yield self.env.timeout(PROCESSING_DELAY)
            attempts = self.geometric_attempts(0.5)
            emit_event(self.env.now, self.model, "verification", {"success": 1, "attempts": int(attempts)})
            yield self.out.put(msg)


class BPM:
    def __init__(self, env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store, bank: BankState,
                 logger: logging.Logger):
        self.env = env
        self.inp = in_store
        self.out = out_store
        self.bank = bank
        self.logger = logger
        self.model = "BPM1"

    def run(self):
        while True:
            msg = yield self.inp.get()
            yield self.env.timeout(PROCESSING_DELAY)

            # Reserve funds so multiple in-flight transactions don't overdraft.
            with self.bank.lock.request() as req:
                yield req
                avail = self.bank.available()
                max_amount = min(40, avail)
                amount = random.randint(0, max_amount) if max_amount > 0 else 0
                self.bank.reserved += amount

            emit_event(self.env.now, self.model, "bill", {"amount": int(amount)})
            yield self.out.put({"id": msg["id"], "amount": int(amount)})


class TPM:
    def __init__(self, env: simpy.Environment, in_store: simpy.Store, bank: BankState, logger: logging.Logger):
        self.env = env
        self.inp = in_store
        self.bank = bank
        self.logger = logger
        self.model = "TPM1"

    def run(self):
        while True:
            msg = yield self.inp.get()
            amount = int(msg.get("amount", 0))
            yield self.env.timeout(PROCESSING_DELAY)

            with self.bank.lock.request() as req:
                yield req
                # Apply transaction
                self.bank.balance -= amount
                self.bank.reserved -= amount
                self.bank.count += 1
                remaining = int(self.bank.balance)
                count = int(self.bank.count)

            emit_event(self.env.now, self.model, "transaction", {"remaining": remaining, "count": count})


def run_simulation(simulation_time: float, logger: logging.Logger) -> None:
    # Seed RNG from system time
    seed = time.time_ns()
    random.seed(seed)
    logger.info("Random seed: %d", seed)

    requests = read_requests_from_stdin(logger)
    logger.info("Loaded %d requests from stdin", len(requests))

    env = simpy.Environment()

    # Stores between components
    s_in_aam = simpy.Store(env)
    s_aam_anv = simpy.Store(env)
    s_anv_pv = simpy.Store(env)
    s_pv_bpm = simpy.Store(env)
    s_bpm_tpm = simpy.Store(env)

    bank = BankState(env=env, balance=3000, reserved=0, count=0)

    # Instantiate components
    input_reader = InputReader(env, s_in_aam, requests, logger)
    aam = AAM(env, s_in_aam, s_aam_anv, logger)
    anv = ANV(env, s_aam_anv, s_anv_pv, logger)
    pv = PV(env, s_anv_pv, s_pv_bpm, logger)
    bpm = BPM(env, s_pv_bpm, s_bpm_tpm, bank, logger)
    tpm = TPM(env, s_bpm_tpm, bank, logger)

    # Register processes
    env.process(input_reader.run())
    env.process(aam.run())
    env.process(anv.run())
    env.process(pv.run())
    env.process(bpm.run())
    env.process(tpm.run())

    # Run with a real-time safety cap (must finish in <= 10 seconds wall time)
    wall_start = time.monotonic()
    wall_limit = 9.5  # seconds (leave buffer)

    until = float(simulation_time)
    if until < 0:
        until = 0.0

    # Step-run to enforce wall clock limit
    try:
        while True:
            if (time.monotonic() - wall_start) > wall_limit:
                logger.warning("Wall-clock limit reached; stopping simulation early at sim_time=%.3f", env.now)
                break

            nxt = env.peek()
            if nxt == float("inf"):
                break  # no more scheduled events
            if nxt > until:
                break
            env.step()

        # If we stopped because nxt > until, advance exactly to 'until' (no events executed at >until anyway)
        # (Not strictly necessary; env.now will be <= until.)
    except Exception as e:
        logger.exception("Simulation error: %s", e)
        raise


def main(argv=None) -> int:
    logger = setup_logging()

    parser = argparse.ArgumentParser(description="IOBS Discrete Event Simulation (SimPy)")
    parser.add_argument("--simulation_time", type=float, default=1000000.0,
                        help="Total simulation time in seconds (default: 1000000.0)")
    args = parser.parse_args(argv)

    run_simulation(args.simulation_time, logger)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())