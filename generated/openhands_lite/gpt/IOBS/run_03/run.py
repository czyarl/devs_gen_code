#!/usr/bin/env python3
import argparse
import json
import logging
import random
import sys
import time
from dataclasses import dataclass
from typing import Iterable, Iterator, TextIO

import simpy


PROCESSING_DELAY = 10.0


def _emit(time_value: float, model: str, event: str, data: dict) -> None:
    sys.stdout.write(json.dumps({"time": float(time_value), "model": model, "event": event, "data": data}) + "\n")
    sys.stdout.flush()


def _parse_timestamp_to_seconds(ts: str) -> float:
    hh, mm, ss, mmm = ts.split(":")
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(mmm) / 1000.0


@dataclass(frozen=True)
class Request:
    arrival_time: float
    valid: int
    invalid: int


def _read_requests(stdin: TextIO) -> Iterator[Request]:
    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        if "#" in line:
            line = line.split("#", 1)[0].strip()
        if not line:
            continue

        parts = line.split()
        if len(parts) != 3:
            logging.warning("Skipping malformed input line: %r", raw.rstrip("\n"))
            continue

        ts, valid_s, invalid_s = parts
        try:
            arrival = _parse_timestamp_to_seconds(ts)
            valid = int(valid_s)
            invalid = int(invalid_s)
        except ValueError:
            logging.warning("Skipping unparsable input line: %r", raw.rstrip("\n"))
            continue

        yield Request(arrival_time=arrival, valid=valid, invalid=invalid)


@dataclass
class SystemState:
    balance: int = 3000
    transaction_count: int = 0


def _handle_request(env: simpy.Environment, req: Request, pipeline: simpy.Resource, state: SystemState) -> Iterable[simpy.events.Event]:
    if req.arrival_time > env.now:
        yield env.timeout(req.arrival_time - env.now)

    _emit(env.now, "input_reader1", "input", {"valid": req.valid, "invalid": req.invalid})

    with pipeline.request() as token:
        yield token

        yield env.timeout(PROCESSING_DELAY)
        if req.valid == 1 and req.invalid == 0:
            _emit(env.now, "AAM1", "account_generated", {})
        elif req.valid == 1 and req.invalid == 1:
            _emit(env.now, "AAM1", "logout", {})
            return
        else:
            _emit(env.now, "AAM1", "logout", {})
            return

        yield env.timeout(PROCESSING_DELAY)
        passed = 1 if random.random() < 0.5 else 0
        _emit(env.now, "ANV1", "verification", {"pass": passed, "fail": 1 - passed})
        if not passed:
            return

        attempts = 1
        while random.random() >= 0.5:
            attempts += 1

        yield env.timeout(PROCESSING_DELAY)
        _emit(env.now, "PV1", "verification", {"success": 1, "attempts": attempts})

        yield env.timeout(PROCESSING_DELAY)
        max_amount = min(40, max(0, state.balance))
        amount = int(random.randint(0, max_amount))
        _emit(env.now, "BPM1", "bill", {"amount": amount})

        yield env.timeout(PROCESSING_DELAY)
        state.balance -= amount
        state.transaction_count += 1
        _emit(env.now, "TPM1", "transaction", {"remaining": int(state.balance), "count": int(state.transaction_count)})


def _input_reader(env: simpy.Environment, requests: Iterable[Request], pipeline: simpy.Resource, state: SystemState) -> Iterable[simpy.events.Event]:
    _emit(env.now, "input_reader1", "start", {})
    for req in requests:
        env.process(_handle_request(env, req, pipeline, state))
    yield env.timeout(0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Internet Online Banking System (IOBS) DES simulator")
    parser.add_argument("--simulation_time", type=float, default=1000000.0, help="Total simulation time in seconds")
    args = parser.parse_args(argv)

    seed = time.time_ns()
    random.seed(seed)

    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.info("Seed: %s", seed)

    env = simpy.Environment()
    pipeline = simpy.Resource(env, capacity=1)
    state = SystemState(balance=3000, transaction_count=0)

    reqs = list(_read_requests(sys.stdin))
    env.process(_input_reader(env, reqs, pipeline, state))

    try:
        env.run(until=float(args.simulation_time))
    except Exception:
        logging.exception("Simulation crashed")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
