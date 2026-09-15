#!/usr/bin/env python3
import argparse
import json
import logging
import random
import sys
import time
from dataclasses import dataclass

import simpy

try:
    import xdevs  # noqa: F401
except Exception:  # pragma: no cover
    xdevs = None  # type: ignore


DELAY = 10.0


@dataclass
class BankState:
    balance: int = 3000
    reserved: int = 0
    count: int = 0


def parse_timestamp_to_seconds(ts: str) -> float:
    parts = ts.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid timestamp: {ts!r}")
    hh, mm, ss, mmm = (int(p) for p in parts)
    return hh * 3600.0 + mm * 60.0 + ss + (mmm / 1000.0)


def emit(now: float, model: str, event: str, data: dict) -> None:
    obj = {"time": float(now), "model": model, "event": event, "data": data}
    sys.stdout.write(json.dumps(obj) + "\n")


def input_arrival(env: simpy.Environment, t: float, valid: int, invalid: int, aam_in: simpy.Store):
    if t > env.now:
        yield env.timeout(t - env.now)
    emit(env.now, "input_reader1", "input", {"valid": int(valid), "invalid": int(invalid)})
    yield aam_in.put({"valid": int(valid), "invalid": int(invalid)})


def aam_worker(env: simpy.Environment, aam_in: simpy.Store, anv_in: simpy.Store):
    while True:
        req = yield aam_in.get()
        yield env.timeout(DELAY)
        if int(req.get("invalid", 0)) == 1:
            emit(env.now, "AAM1", "logout", {})
            continue
        emit(env.now, "AAM1", "account_generated", {})
        yield anv_in.put(req)


def anv_worker(env: simpy.Environment, anv_in: simpy.Store, pv_in: simpy.Store):
    while True:
        req = yield anv_in.get()
        yield env.timeout(DELAY)
        passed = 1 if random.random() < 0.5 else 0
        failed = 1 - passed
        emit(env.now, "ANV1", "verification", {"pass": passed, "fail": failed})
        if passed:
            yield pv_in.put(req)


def pv_worker(env: simpy.Environment, pv_in: simpy.Store, bpm_in: simpy.Store):
    while True:
        req = yield pv_in.get()
        yield env.timeout(DELAY)

        attempts = 0
        # Geometric(p=0.5), forced to succeed within a sane cap.
        while True:
            attempts += 1
            if random.random() < 0.5 or attempts >= 10_000:
                break

        emit(env.now, "PV1", "verification", {"success": 1, "attempts": int(attempts)})
        yield bpm_in.put(req)


def bpm_worker(
    env: simpy.Environment,
    bpm_in: simpy.Store,
    tpm_in: simpy.Store,
    bank: BankState,
    bank_lock: simpy.Resource,
):
    while True:
        req = yield bpm_in.get()
        yield env.timeout(DELAY)

        with bank_lock.request() as lock_req:
            yield lock_req
            available = max(0, int(bank.balance) - int(bank.reserved))
            max_amt = min(40, available)
            amount = random.randint(0, max_amt) if max_amt > 0 else 0
            bank.reserved += int(amount)

        emit(env.now, "BPM1", "bill", {"amount": int(amount)})
        req2 = dict(req)
        req2["amount"] = int(amount)
        yield tpm_in.put(req2)


def tpm_worker(
    env: simpy.Environment,
    tpm_in: simpy.Store,
    bank: BankState,
    bank_lock: simpy.Resource,
):
    while True:
        req = yield tpm_in.get()
        yield env.timeout(DELAY)

        amount = int(req.get("amount", 0))
        with bank_lock.request() as lock_req:
            yield lock_req
            bank.reserved = max(0, int(bank.reserved) - amount)
            bank.balance = max(0, int(bank.balance) - amount)
            bank.count += 1
            remaining = int(bank.balance)
            count = int(bank.count)

        emit(env.now, "TPM1", "transaction", {"remaining": remaining, "count": count})


def run_with_wallclock_limit(env: simpy.Environment, until: float, max_wall_seconds: float = 9.5) -> None:
    start = time.monotonic()
    from simpy.core import EmptySchedule

    while True:
        if time.monotonic() - start > max_wall_seconds:
            logging.warning(
                "Wall-clock limit reached; stopping early at sim_time=%.3f", env.now
            )
            return
        next_t = env.peek()
        if next_t == float("inf"):
            return
        if next_t > until:
            return
        try:
            env.step()
        except EmptySchedule:
            return


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--simulation_time",
        type=float,
        default=1000000.0,
        help="Total simulation time in seconds.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s:%(name)s:%(message)s",
    )

    random.seed(time.time_ns())

    env = simpy.Environment()

    aam_in = simpy.Store(env)
    anv_in = simpy.Store(env)
    pv_in = simpy.Store(env)
    bpm_in = simpy.Store(env)
    tpm_in = simpy.Store(env)

    bank = BankState(balance=3000, reserved=0, count=0)
    bank_lock = simpy.Resource(env, capacity=1)

    env.process(aam_worker(env, aam_in, anv_in))
    env.process(anv_worker(env, anv_in, pv_in))
    env.process(pv_worker(env, pv_in, bpm_in))
    env.process(bpm_worker(env, bpm_in, tpm_in, bank, bank_lock))
    env.process(tpm_worker(env, tpm_in, bank, bank_lock))

    emit(0.0, "input_reader1", "start", {})

    line_no = 0
    for raw in sys.stdin:
        line_no += 1
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        try:
            ts, valid_s, invalid_s = line.split()
            t = parse_timestamp_to_seconds(ts)
            valid = int(valid_s)
            invalid = int(invalid_s)
        except Exception as e:
            logging.warning("Skipping invalid input line %d: %r (%s)", line_no, raw.rstrip("\n"), e)
            continue

        if t < 0:
            logging.warning("Skipping negative timestamp on line %d: %r", line_no, raw.rstrip("\n"))
            continue

        env.process(input_arrival(env, t, valid, invalid, aam_in))

    sys.stdout.flush()

    until = float(args.simulation_time)
    if until < 0:
        until = 0.0

    run_with_wallclock_limit(env, until=until, max_wall_seconds=9.5)
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
