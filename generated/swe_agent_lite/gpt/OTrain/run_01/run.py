#!/usr/bin/env python3
"""Ottawa O-Train Light Rail discrete-event simulation.

Entry point: python run.py

Outputs JSONL events to stdout. Logs/debug to stderr.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import random
from collections import deque, defaultdict

import simpy


STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro",
}

ROUTE = [
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

TRAVEL_INTERVAL_S = 225
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
            f"Invalid --simulate_time '{s}'. Expected HH:MM:SS:mmm"
        ) from e


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class EventSink:
    def __init__(self, out_stream=sys.stdout):
        self.out = out_stream

    def emit(self, *, time_s: float, event: str, entity_type: str, station_id: int, payload: dict):
        obj = {
            "time": round(float(time_s), 3),
            "event": event,
            "entity_type": entity_type,
            "station_id": int(station_id),
            "station": STATIONS[int(station_id)],
            "payload": payload,
        }
        self.out.write(json.dumps(obj) + "\n")


class Passenger:
    __slots__ = ("passenger_id", "passenger_num", "origin", "destination")

    def __init__(self, passenger_id: int, passenger_num: int, origin: int, destination: int):
        self.passenger_id = int(passenger_id)
        self.passenger_num = int(passenger_num)
        self.origin = int(origin)
        self.destination = int(destination)

    def payload(self) -> dict:
        return {
            "passenger_id": self.passenger_id,
            "passenger_num": self.passenger_num,
            "origin": self.origin,
            "destination": self.destination,
        }


class StationQueue:
    def __init__(self, station_id: int):
        self.station_id = int(station_id)
        self.q = deque()

    def put(self, p: Passenger):
        # Validation per spec
        if p.origin != self.station_id:
            return
        if p.destination == p.origin:
            return
        self.q.append(p)

    def pop(self) -> Passenger | None:
        if not self.q:
            return None
        return self.q.popleft()

    def __len__(self):
        return len(self.q)


class Train:
    def __init__(self):
        # destination -> deque[Passenger]
        self.by_dest = defaultdict(deque)

    def board(self, p: Passenger):
        self.by_dest[p.destination].append(p)

    def alight_all_for(self, station_id: int):
        dq = self.by_dest.get(int(station_id))
        if not dq:
            return []
        out = list(dq)
        dq.clear()
        return out


def passenger_generator(env: simpy.Environment, station_id: int, station_queue: StationQueue, sink: EventSink):
    """Generate passengers for a station."""
    # Initialization passenger at t=0.5
    yield env.timeout(0.5)
    origin = station_id
    destination = random.choice([sid for sid in STATIONS.keys() if sid != origin])
    p0 = Passenger(0, 0, origin, destination)
    station_queue.put(p0)
    sink.emit(
        time_s=env.now,
        event="passenger_generated",
        entity_type="passenger_generator",
        station_id=station_id,
        payload=p0.payload(),
    )

    passenger_num = 1
    while True:
        # Normal(mean=5min, std=5min), clamp [1,9] minutes, convert to seconds, round to nearest int
        interval_min = random.gauss(5.0, 5.0)
        interval_min = clamp(interval_min, 1.0, 9.0)
        interval_s = int(round(interval_min * 60.0))
        yield env.timeout(interval_s)

        destination = random.choice([sid for sid in STATIONS.keys() if sid != origin])
        passenger_id = passenger_num * 100 + origin * 10 + destination
        p = Passenger(passenger_id, passenger_num, origin, destination)
        station_queue.put(p)
        sink.emit(
            time_s=env.now,
            event="passenger_generated",
            entity_type="passenger_generator",
            station_id=station_id,
            payload=p.payload(),
        )
        passenger_num += 1


def train_scheduler(env: simpy.Environment, station_queues: dict[int, StationQueue], train: Train, sink: EventSink):
    """Move train along fixed route and trigger arrival, alighting, boarding."""
    route_idx = 0

    # Initial arrival at t=0.0 at Bayview dir=0
    station_id, direction = ROUTE[route_idx]
    sink.emit(
        time_s=env.now,
        event="train_arrival",
        entity_type="train",
        station_id=station_id,
        payload={"station": station_id, "direction": direction},
    )

    # Handle alighting then boarding at initial stop
    yield from handle_stop(env, station_id, station_queues[station_id], train, sink)

    while True:
        # advance to next stop
        route_idx = (route_idx + 1) % len(ROUTE)
        yield env.timeout(TRAVEL_INTERVAL_S)
        station_id, direction = ROUTE[route_idx]

        sink.emit(
            time_s=env.now,
            event="train_arrival",
            entity_type="train",
            station_id=station_id,
            payload={"station": station_id, "direction": direction},
        )

        yield from handle_stop(env, station_id, station_queues[station_id], train, sink)


def handle_stop(env: simpy.Environment, station_id: int, station_queue: StationQueue, train: Train, sink: EventSink):
    """At a stop: serial alighting then serial boarding."""
    # Alight passengers destined here
    exiting = train.alight_all_for(station_id)
    for i, p in enumerate(exiting):
        yield env.timeout(SERIAL_DELAY_S if i == 0 else SERIAL_DELAY_S)
        sink.emit(
            time_s=env.now,
            event="passenger_exiting",
            entity_type="train_queue",
            station_id=station_id,
            payload=p.payload(),
        )

    # Board passengers waiting here
    boarded_i = 0
    while len(station_queue) > 0:
        p = station_queue.pop()
        if p is None:
            break
        yield env.timeout(SERIAL_DELAY_S if boarded_i == 0 else SERIAL_DELAY_S)
        train.board(p)
        sink.emit(
            time_s=env.now,
            event="passenger_boarding",
            entity_type="station_queue",
            station_id=station_id,
            payload=p.payload(),
        )
        boarded_i += 1


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="O-Train Light Rail DES simulation")
    p.add_argument(
        "--simulate_time",
        type=parse_sim_time_hhmmssmmm,
        default=parse_sim_time_hhmmssmmm("00:01:00:000"),
        help='Simulation duration in "HH:MM:SS:mmm" (default: 00:01:00:000)',
    )
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s:%(message)s")

    args = build_arg_parser().parse_args(argv)

    # Seed randomness from system time
    random.seed(time.time_ns())

    env = simpy.Environment()
    sink = EventSink(sys.stdout)

    station_queues = {sid: StationQueue(sid) for sid in STATIONS.keys()}
    train = Train()

    # Start passenger generators
    for sid in STATIONS.keys():
        env.process(passenger_generator(env, sid, station_queues[sid], sink))

    # Start train scheduler
    env.process(train_scheduler(env, station_queues, train, sink))

    # Run simulation
    sim_duration = float(args.simulate_time)
    env.run(until=sim_duration)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
