#!/usr/bin/env python3
"""O-Train Light Rail DES simulation (SimPy).

Outputs JSONL events to stdout only. Logs go to stderr.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Tuple

import simpy


STATIONS: Dict[int, str] = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro",
}


def parse_sim_time_hhmmssmmm(s: str) -> float:
    """Parse HH:MM:SS:mmm into seconds (float)."""
    try:
        hh, mm, ss, mmm = s.split(":")
        return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(mmm) / 1000.0
    except Exception as e:
        raise argparse.ArgumentTypeError(f"Invalid --simulate_time '{s}'. Expected HH:MM:SS:mmm") from e


def jprint(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


@dataclass(frozen=True)
class Passenger:
    passenger_id: int
    passenger_num: int
    origin: int
    destination: int

    def payload(self) -> dict:
        return {
            "passenger_id": self.passenger_id,
            "passenger_num": self.passenger_num,
            "origin": self.origin,
            "destination": self.destination,
        }


class StationQueue:
    def __init__(self, station_id: int):
        self.station_id = station_id
        self.q: Deque[Passenger] = deque()

    def put(self, p: Passenger) -> None:
        # Validation per spec
        if p.origin != self.station_id:
            return
        if p.destination == p.origin:
            return
        self.q.append(p)

    def pop(self) -> Optional[Passenger]:
        if not self.q:
            return None
        return self.q.popleft()

    def __len__(self) -> int:
        return len(self.q)


class Train:
    def __init__(self):
        # destination -> deque of passengers (preserve boarding order within destination)
        self.by_dest: Dict[int, Deque[Passenger]] = {sid: deque() for sid in STATIONS}

    def board(self, p: Passenger) -> None:
        self.by_dest[p.destination].append(p)

    def alight_all_for(self, station_id: int) -> List[Passenger]:
        dq = self.by_dest[station_id]
        out: List[Passenger] = list(dq)
        dq.clear()
        return out


def emit_event(env: simpy.Environment, event: str, entity_type: str, station_id: int, payload: dict) -> None:
    obj = {
        "time": round(float(env.now), 3),
        "event": event,
        "entity_type": entity_type,
        "station_id": int(station_id),
        "station": STATIONS[int(station_id)],
        "payload": payload,
    }
    jprint(obj)


def passenger_generator(env: simpy.Environment, station_id: int, station_q: StationQueue, rng: random.Random):
    # Initialization passenger at t=0.5
    yield env.timeout(0.5)
    init_dest = rng.choice([d for d in STATIONS.keys() if d != station_id])
    p0 = Passenger(passenger_id=0, passenger_num=0, origin=station_id, destination=init_dest)
    station_q.put(p0)
    emit_event(env, "passenger_generated", "passenger_generator", station_id, p0.payload())

    passenger_num = 1
    while True:
        # Normal(mean=5min, std=5min), clamp [1,9] minutes, convert to seconds, round to nearest int
        minutes = rng.normalvariate(5.0, 5.0)
        minutes = clamp(minutes, 1.0, 9.0)
        interval_s = int(round(minutes * 60.0))
        yield env.timeout(interval_s)

        dest = rng.choice([d for d in STATIONS.keys() if d != station_id])
        passenger_id = passenger_num * 100 + station_id * 10 + dest
        p = Passenger(passenger_id=passenger_id, passenger_num=passenger_num, origin=station_id, destination=dest)
        station_q.put(p)
        emit_event(env, "passenger_generated", "passenger_generator", station_id, p.payload())
        passenger_num += 1


ROUTE: List[Tuple[int, int]] = [
    (1, 0),
    (2, 0),
    (3, 0),
    (4, 0),
    (5, 1),
    (4, 1),
    (3, 1),
    (2, 1),
    (1, 0),
]


def train_process(env: simpy.Environment, train: Train, station_queues: Dict[int, StationQueue]):
    travel_interval = 225.0
    dwell_step = 0.025

    idx = 0
    # initial arrival at t=0 at Bayview dir=0
    while True:
        station_id, direction = ROUTE[idx]
        emit_event(
            env,
            "train_arrival",
            "train",
            station_id,
            {"station": station_id, "direction": direction},
        )

        # Alighting first (serial)
        alighters = train.alight_all_for(station_id)
        for i, p in enumerate(alighters):
            yield env.timeout(dwell_step)
            emit_event(env, "passenger_exiting", "train_queue", station_id, p.payload())

        # Boarding next (serial)
        q = station_queues[station_id]
        first = True
        while len(q) > 0:
            p = q.pop()
            if p is None:
                break
            yield env.timeout(dwell_step)
            train.board(p)
            emit_event(env, "passenger_boarding", "station_queue", station_id, p.payload())
            first = False

        # Move to next station
        idx = (idx + 1) % len(ROUTE)
        yield env.timeout(travel_interval)


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="O-Train Light Rail Simulation (DES)")
    ap.add_argument(
        "--simulate_time",
        type=str,
        default="00:01:00:000",
        help='Simulation duration in "HH:MM:SS:mmm" (default: 00:01:00:000)',
    )
    return ap


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s:%(message)s")

    args = build_arg_parser().parse_args(argv)
    sim_duration = parse_sim_time_hhmmssmmm(args.simulate_time)

    # Seed RNG with system time
    seed = time.time_ns()
    rng = random.Random(seed)
    logging.info("seed=%s simulate_time=%ss", seed, sim_duration)

    env = simpy.Environment()

    station_queues: Dict[int, StationQueue] = {sid: StationQueue(sid) for sid in STATIONS}
    train = Train()

    # Start passenger generators
    for sid in STATIONS:
        env.process(passenger_generator(env, sid, station_queues[sid], rng))

    # Start train
    env.process(train_process(env, train, station_queues))

    # Run
    env.run(until=sim_duration)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
