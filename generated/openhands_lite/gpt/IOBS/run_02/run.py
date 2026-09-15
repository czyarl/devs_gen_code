import argparse
import json
import logging
import random
import sys
import time

import simpy


PROCESSING_DELAY = 10.0


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stderr,
    )


def _emit(env, model, event, data) -> None:
    sys.stdout.write(
        json.dumps(
            {
                "time": float(env.now),
                "model": str(model),
                "event": str(event),
                "data": data,
            },
            separators=(",", ":"),
        )
        + "\n"
    )
    sys.stdout.flush()


def _parse_timestamp_to_seconds(ts: str) -> float:
    # Format: HH:MM:SS:mmm
    parts = ts.strip().split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid timestamp format: {ts!r}")
    hh, mm, ss, mmm = (int(p) for p in parts)
    return hh * 3600 + mm * 60 + ss + (mmm / 1000.0)


def _read_inputs_from_stdin():
    items = []
    for idx, raw in enumerate(sys.stdin):
        line = raw.strip()
        if not line:
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
        fields = line.split()
        if len(fields) < 3:
            logging.warning("Skipping malformed line: %r", raw.rstrip("\n"))
            continue
        try:
            t = _parse_timestamp_to_seconds(fields[0])
            valid = int(fields[1])
            invalid = int(fields[2])
        except Exception:
            logging.warning("Skipping malformed line: %r", raw.rstrip("\n"))
            continue
        items.append((t, valid, invalid, idx))

    # Sort by timestamp, preserve original order for ties.
    items.sort(key=lambda x: (x[0], x[3]))
    return items


class TPMState:
    def __init__(self, balance=3000):
        self.balance = int(balance)
        self.count = 0


def input_reader1(env, out_store, inputs):
    _emit(env, "input_reader1", "start", {})

    for t, valid, invalid, _ in inputs:
        if t < env.now:
            # If inputs were unsorted or duplicated oddly, emit immediately.
            t = env.now
        yield env.timeout(t - env.now)
        _emit(env, "input_reader1", "input", {"valid": int(valid), "invalid": int(invalid)})
        yield out_store.put({"valid": int(valid), "invalid": int(invalid)})


def aam1(env, in_store, out_store):
    while True:
        msg = yield in_store.get()
        yield env.timeout(PROCESSING_DELAY)

        valid = int(msg.get("valid", 0))
        invalid = int(msg.get("invalid", 0))

        if valid == 1 and invalid == 0:
            _emit(env, "AAM1", "account_generated", {})
            yield out_store.put(msg)
        else:
            _emit(env, "AAM1", "logout", {})


def anv1(env, in_store, out_store):
    while True:
        msg = yield in_store.get()
        yield env.timeout(PROCESSING_DELAY)

        passed = 1 if (random.random() < 0.5) else 0
        failed = 1 - passed
        _emit(env, "ANV1", "verification", {"pass": int(passed), "fail": int(failed)})

        if passed:
            yield out_store.put(msg)


def _sample_attempts_p05():
    # Geometric(p=0.5): attempts in {1,2,...}
    attempts = 0
    while True:
        x = random.getrandbits(64)
        if x:
            attempts += (x & -x).bit_length()
            return int(attempts)
        attempts += 64


def pv1(env, in_store, out_store):
    while True:
        msg = yield in_store.get()
        yield env.timeout(PROCESSING_DELAY)

        attempts = _sample_attempts_p05()
        _emit(env, "PV1", "verification", {"success": 1, "attempts": int(attempts)})
        yield out_store.put(msg)


def bpm1(env, in_store, out_store, tpm_state, account_lock):
    while True:
        msg = yield in_store.get()

        lock_req = account_lock.request()
        yield lock_req

        yield env.timeout(PROCESSING_DELAY)
        max_amt = min(40, max(0, int(tpm_state.balance)))
        amount = int(random.randint(0, max_amt))
        _emit(env, "BPM1", "bill", {"amount": int(amount)})

        yield out_store.put({"amount": amount, "lock_req": lock_req})


def tpm1(env, in_store, tpm_state, account_lock):
    while True:
        msg = yield in_store.get()
        yield env.timeout(PROCESSING_DELAY)

        amount = int(msg.get("amount", 0))
        amount = max(0, min(amount, tpm_state.balance))

        tpm_state.balance -= amount
        tpm_state.count += 1

        _emit(
            env,
            "TPM1",
            "transaction",
            {"remaining": int(tpm_state.balance), "count": int(tpm_state.count)},
        )

        lock_req = msg.get("lock_req")
        if lock_req is not None:
            account_lock.release(lock_req)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args(argv)

    _setup_logging()

    # Use system time to seed randomness.
    seed = time.time_ns()
    random.seed(seed)

    inputs = _read_inputs_from_stdin()

    env = simpy.Environment()
    aam_in = simpy.Store(env)
    anv_in = simpy.Store(env)
    pv_in = simpy.Store(env)
    bpm_in = simpy.Store(env)
    tpm_in = simpy.Store(env)

    tpm_state = TPMState()
    account_lock = simpy.Resource(env, capacity=1)

    env.process(input_reader1(env, aam_in, inputs))
    env.process(aam1(env, aam_in, anv_in))
    env.process(anv1(env, anv_in, pv_in))
    env.process(pv1(env, pv_in, bpm_in))
    env.process(bpm1(env, bpm_in, tpm_in, tpm_state, account_lock))
    env.process(tpm1(env, tpm_in, tpm_state, account_lock))

    # Run using simulation time; no real-time delays.
    env.run(until=float(args.simulation_time))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
