#!/usr/bin/env python3
import argparse
import sys
import json
import logging
import random
import time
from dataclasses import dataclass
import simpy

# Required by the prompt (available in the environment). Not used directly.
import xdevs  # noqa: F401


PROCESSING_DELAY = 10.0


def parse_timestamp_to_seconds(ts: str) -> float:
    # Format: HH:MM:SS:mmm
    parts = ts.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Bad timestamp format: {ts!r}")
    hh, mm, ss, mmm = parts
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(mmm) / 1000.0


def emit(env: simpy.Environment, model: str, event: str, data: dict) -> None:
    obj = {"time": float(env.now), "model": model, "event": event, "data": data}
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")


@dataclass
class Request:
    rid: int
    t: float
    valid: int
    invalid: int


class AccountState:
    """
    Shared account state. We reserve funds in BPM to guarantee the generated bill
    amount never exceeds remaining available balance even with concurrent inflight requests.
    """
    def __init__(self, env: simpy.Environment, initial_balance: int = 3000):
        self.env = env
        self.balance = int(initial_balance)
        self.reserved = 0
        self.count = 0
        self.lock = simpy.Resource(env, capacity=1)


def input_reader1(env: simpy.Environment, requests: list[Request], out_store: simpy.Store) -> None:
    emit(env, "input_reader1", "start", {})
    current = 0.0
    for req in requests:
        dt = req.t - current
        if dt < -1e-9:
            # Should not happen after sorting.
            dt = 0.0
        if dt > 0:
            yield env.timeout(dt)
        else:
            # Same-timestamp (or numerically extremely close) requests: no time advance.
            yield env.timeout(0)
        current = req.t
        emit(env, "input_reader1", "input", {"valid": int(req.valid), "invalid": int(req.invalid)})
        yield out_store.put({"rid": req.rid, "valid": int(req.valid), "invalid": int(req.invalid)})


def AAM1(env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store) -> None:
    while True:
        msg = yield in_store.get()
        yield env.timeout(PROCESSING_DELAY)
        if int(msg.get("valid", 0)) == 1 and int(msg.get("invalid", 0)) == 0:
            emit(env, "AAM1", "account_generated", {})
            yield out_store.put({"rid": msg["rid"]})
        else:
            emit(env, "AAM1", "logout", {})
            # End processing for this request.


def ANV1(env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store) -> None:
    while True:
        msg = yield in_store.get()
        yield env.timeout(PROCESSING_DELAY)
        passed = 1 if random.random() < 0.5 else 0
        failed = 1 - passed
        emit(env, "ANV1", "verification", {"pass": passed, "fail": failed})
        if passed:
            yield out_store.put({"rid": msg["rid"]})
        # If failed: end processing.


def PV1(env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store) -> None:
    while True:
        msg = yield in_store.get()
        yield env.timeout(PROCESSING_DELAY)
        # Try until success (geometric with p=0.5). Attempts do not add extra time here.
        attempts = 1
        while True:
            if random.random() < 0.5:
                break
            attempts += 1
        emit(env, "PV1", "verification", {"success": 1, "attempts": int(attempts)})
        yield out_store.put({"rid": msg["rid"]})


def BPM1(env: simpy.Environment, in_store: simpy.Store, out_store: simpy.Store, acct: AccountState) -> None:
    while True:
        msg = yield in_store.get()
        yield env.timeout(PROCESSING_DELAY)
        # Reserve funds so the bill amount cannot exceed remaining available balance.
        with acct.lock.request() as req:
            yield req
            available = acct.balance - acct.reserved
            if available < 0:
                available = 0
            upper = min(40, available)
            amount = random.randint(0, int(upper)) if upper > 0 else 0
            acct.reserved += int(amount)
        emit(env, "BPM1", "bill", {"amount": int(amount)})
        yield out_store.put({"rid": msg["rid"], "amount": int(amount)})


def TPM1(env: simpy.Environment, in_store: simpy.Store, acct: AccountState) -> None:
    while True:
        msg = yield in_store.get()
        yield env.timeout(PROCESSING_DELAY)
        amount = int(msg.get("amount", 0))
        with acct.lock.request() as req:
            yield req
            # Commit the reserved payment.
            if amount > acct.balance:
                # Shouldn't happen due to reservation, but keep safe.
                amount = acct.balance
            acct.balance -= amount
            acct.reserved -= amount
            if acct.reserved < 0:
                acct.reserved = 0
            acct.count += 1
            remaining = acct.balance
            count = acct.count
        emit(env, "TPM1", "transaction", {"remaining": int(remaining), "count": int(count)})


def read_requests_from_stdin(logger: logging.Logger) -> list[Request]:
    requests: list[Request] = []
    rid = 0
    for line_no, raw in enumerate(sys.stdin, start=1):
        line = raw.strip()
        if not line:
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
        parts = line.split()
        if len(parts) != 3:
            logger.warning("Skipping malformed line %d: %r", line_no, raw.rstrip("\n"))
            continue
        ts_s, valid_s, invalid_s = parts
        try:
            t = parse_timestamp_to_seconds(ts_s)
            valid = int(valid_s)
            invalid = int(invalid_s)
        except Exception as e:
            logger.warning("Skipping line %d due to parse error (%s): %r", line_no, e, raw.rstrip("\n"))
            continue
        requests.append(Request(rid=rid, t=float(t), valid=valid, invalid=invalid))
        rid += 1

    # Sort by time, stable by rid to preserve stdin order for identical timestamps.
    requests.sort(key=lambda r: (r.t, r.rid))
    return requests


def compute_stop_time(simulation_time: float, requests: list[Request]) -> float:
    if not requests:
        return min(simulation_time, 0.0)
    last_input = max(r.t for r in requests)
    n = len(requests)
    # For a 5-stage pipeline with service time 10, a safe completion bound is:
    # last_input_time + 10*(n + 4). (Deterministic tandem line bound)
    needed = last_input + PROCESSING_DELAY * (n + 4)
    return min(float(simulation_time), float(needed))


def main() -> None:
    parser = argparse.ArgumentParser(description="IOBS DES simulation (SimPy).")
    parser.add_argument("--simulation_time", type=float, default=1000000.0,
                        help="Total simulation time in seconds (default: 1000000.0)")
    args = parser.parse_args()

    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s:%(message)s")
    logger = logging.getLogger("iobs")

    # Seed RNG from system time.
    random.seed(time.time_ns())

    requests = read_requests_from_stdin(logger)

    env = simpy.Environment()

    # Stores (queues) between stages
    s_in_to_aam = simpy.Store(env)
    s_aam_to_anv = simpy.Store(env)
    s_anv_to_pv = simpy.Store(env)
    s_pv_to_bpm = simpy.Store(env)
    s_bpm_to_tpm = simpy.Store(env)

    acct = AccountState(env, initial_balance=3000)

    # Start processes
    env.process(input_reader1(env, requests, s_in_to_aam))
    env.process(AAM1(env, s_in_to_aam, s_aam_to_anv))
    env.process(ANV1(env, s_aam_to_anv, s_anv_to_pv))
    env.process(PV1(env, s_anv_to_pv, s_pv_to_bpm))
    env.process(BPM1(env, s_pv_to_bpm, s_bpm_to_tpm, acct))
    env.process(TPM1(env, s_bpm_to_tpm, acct))

    stop_time = compute_stop_time(args.simulation_time, requests)
    logger.info("Requests=%d stop_time=%.3f (simulation_time=%.3f)", len(requests), stop_time, args.simulation_time)

    # Run the simulation (no real-time waiting).
    env.run(until=stop_time)


if __name__ == "__main__":
    main()