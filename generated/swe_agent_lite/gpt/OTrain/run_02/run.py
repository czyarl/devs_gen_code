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


STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro",
}

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

TRAVEL_INTERVAL_S = 225.0
SERIAL_DELAY_S = 0.025


def parse_sim_time_hhmmssmmm(s: str) -> float:
    """Parse HH:MM:SS:mmm into seconds (float)."""
    try:
        hh, mm, ss, mmm = s.split(":")
        total = (
            int(hh) * 3600
            + int(mm) * 60
            + int(ss)
            + int(mmm) / 1000.0
        )
        if total < 0:
            raise ValueError
        return float(total)
    except Exception as e:
        raise argparse.ArgumentTypeError(
            "--simulate_time must be in HH:MM:SS:mmm format"
        ) from e


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


@dataclass(frozen=True)
class Passenger:
    passenger_id: int
    passenger_num: int
    origin: int
    destination: int

    def payload(self) -> Dict[str, int]:
        return {
            "passenger_id": int(self.passenger_id),
            "passenger_num": int(self.passenger_num),
            "origin": int(self.origin),
            "destination": int(self.destination),
        }


class EventSink:
    def __init__(self) -> None:
        self.out = sys.stdout

    def emit(self, *, t: float, event: str, entity_type: str, station_id: int, payload: Dict) -> None:
        obj = {
            "time": round(float(t), 3),
            "event": event,
            "entity_type": entity_type,
            "station_id": int(station_id),
            "station": STATIONS[int(station_id)],
            "payload": payload,
        }
        self.out.write(json.dumps(obj) + "\n")


class StationQueue:
    def __init__(self, station_id: int) -> None:
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
    def __init__(self) -> None:
        # destination -> FIFO list
        self.by_dest: Dict[int, Deque[Passenger]] = {sid: deque() for sid in STATIONS}

    def board(self, p: Passenger) -> None:
        self.by_dest[p.destination].append(p)

    def alight_all_for(self, station_id: int) -> List[Passenger]:
        dq = self.by_dest[station_id]
        out: List[Passenger] = list(dq)
        dq.clear()
        return out


def passenger_generator(env: simpy.Environment, station_id: int, station_q: StationQueue, sink: EventSink) -> simpy.events.Event:
    """Generate passengers for a station."""

    def choose_destination(origin: int) -> int:
        choices = [s for s in STATIONS.keys() if s != origin]
        return random.choice(choices)

    # Initialization passenger at t=0.5
    yield env.timeout(0.5)
    init_dest = choose_destination(station_id)
    init_p = Passenger(passenger_id=0, passenger_num=0, origin=station_id, destination=init_dest)
    station_q.put(init_p)
    sink.emit(
        t=env.now,
        event="passenger_generated",
        entity_type="passenger_generator",
        station_id=station_id,
        payload=init_p.payload(),
    )

    passenger_num = 1
    while True:
        # Normal(mean=5min, std=5min), clamp [1,9] minutes, convert to seconds, round to nearest int
        interval_min = random.gauss(5.0, 5.0)
        interval_min = clamp(interval_min, 1.0, 9.0)
        interval_s = int(round(interval_min * 60.0))
        yield env.timeout(interval_s)

        dest = choose_destination(station_id)
        pid = passenger_num * 100 + station_id * 10 + dest
        p = Passenger(passenger_id=pid, passenger_num=passenger_num, origin=station_id, destination=dest)
        station_q.put(p)
        sink.emit(
            t=env.now,
            event="passenger_generated",
            entity_type="passenger_generator",
            station_id=station_id,
            payload=p.payload(),
        )
        passenger_num += 1


def train_process(
    env: simpy.Environment,
    station_queues: Dict[int, StationQueue],
    sink: EventSink,
) -> simpy.events.Event:
    train = Train()

    route_idx = 0
    # Initial arrival at t=0.0 at Bayview dir=0
    while True:
        station_id, direction = ROUTE[route_idx]

        # Train arrival event
        sink.emit(
            t=env.now,
            event="train_arrival",
            entity_type="train",
            station_id=station_id,
            payload={"station": station_id, "direction": direction},
        )

        # Alight passengers destined here (serial)
        exiting = train.alight_all_for(station_id)
        for i, p in enumerate(exiting):
            yield env.timeout(SERIAL_DELAY_S)
            sink.emit(
                t=env.now,
                event="passenger_exiting",
                entity_type="train_queue",
                station_id=station_id,
                payload=p.payload(),
            )

        # Board passengers from station queue (serial)
        sq = station_queues[station_id]
        while len(sq) > 0:
            p = sq.pop()
            if p is None:
                break
            yield env.timeout(SERIAL_DELAY_S)
            train.board(p)
            sink.emit(
                t=env.now,
                event="passenger_boarding",
                entity_type="station_queue",
                station_id=station_id,
                payload=p.payload(),
            )

        # Move to next station
        route_idx = (route_idx + 1) % len(ROUTE)
        yield env.timeout(TRAVEL_INTERVAL_S)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="O-Train Light Rail Simulation (DES)")
    p.add_argument(
        "--simulate_time",
        type=parse_sim_time_hhmmssmmm,
        default=parse_sim_time_hhmmssmmm("00:01:00:000"),
        help='Simulation duration in "HH:MM:SS:mmm" (default: 00:01:00:000)',
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(message)s")

    # Seed randomness from system time
    random.seed(time.time_ns())

    args = build_arg_parser().parse_args(argv)
    sim_duration = float(args.simulate_time)

    env = simpy.Environment()
    sink = EventSink()

    station_queues = {sid: StationQueue(sid) for sid in STATIONS}

    # Start passenger generators
    for sid in STATIONS:
        env.process(passenger_generator(env, sid, station_queues[sid], sink))

    # Start train
    env.process(train_process(env, station_queues, sink))

    # Run simulation
    env.run(until=sim_duration)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
