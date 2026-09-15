#!/usr/bin/env python3
"""O-Train Light Rail discrete-event simulation.

Entry point: python run.py

STDOUT: JSONL events only.
STDERR: logs/debug.

Implements the PR-described scenario using SimPy (DES).
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from collections import defaultdict, deque
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


def parse_simulate_time(value: str) -> float:
    """Parse HH:MM:SS:mmm into seconds (float)."""
    try:
        hh, mm, ss, mmm = value.split(":")
        hours = int(hh)
        minutes = int(mm)
        seconds = int(ss)
        millis = int(mmm)
        if hours < 0 or minutes < 0 or seconds < 0 or millis < 0:
            raise ValueError
        if minutes >= 60 or seconds >= 60 or millis >= 1000:
            raise ValueError
        return hours * 3600 + minutes * 60 + seconds + millis / 1000.0
    except Exception as e:
        raise argparse.ArgumentTypeError(
            "--simulate_time must be in HH:MM:SS:mmm (e.g. 00:01:00:000)"
        ) from e


class JsonlEmitter:
    def __init__(self, out_stream=sys.stdout):
        self._out = out_stream

    @staticmethod
    def _round_time(t: float) -> float:
        # Precision up to milliseconds.
        return round(float(t), 3)

    def emit(
        self,
        *,
        sim_time: float,
        event: str,
        entity_type: str,
        station_id: int,
        payload: dict,
    ) -> None:
        obj = {
            "time": self._round_time(sim_time),
            "event": event,
            "entity_type": entity_type,
            "station_id": int(station_id),
            "station": STATIONS[int(station_id)],
            "payload": payload,
        }
        self._out.write(json.dumps(obj) + "\n")


@dataclass(frozen=True)
class Passenger:
    passenger_id: int
    passenger_num: int
    origin: int
    destination: int

    def payload(self) -> dict:
        return {
            "passenger_id": int(self.passenger_id),
            "passenger_num": int(self.passenger_num),
            "origin": int(self.origin),
            "destination": int(self.destination),
        }


class Station:
    def __init__(self, station_id: int):
        if station_id not in STATIONS:
            raise ValueError("Invalid station_id")
        self.station_id = station_id
        self.queue: Deque[Passenger] = deque()

    def enqueue(self, p: Passenger) -> None:
        # Validation: passengers only join if origin matches this station and destination differs.
        if p.origin != self.station_id:
            return
        if p.destination == p.origin:
            return
        self.queue.append(p)


class Train:
    def __init__(self):
        # passengers grouped by destination station
        self.by_destination: Dict[int, Deque[Passenger]] = defaultdict(deque)

    def board(self, passenger: Passenger) -> None:
        self.by_destination[passenger.destination].append(passenger)

    def pop_alighting(self, station_id: int) -> List[Passenger]:
        dq = self.by_destination.get(station_id)
        if not dq:
            return []
        passengers = list(dq)
        dq.clear()
        return passengers


def sample_generation_interval_seconds() -> int:
    # Normal distribution in minutes, clamped to [1, 9] minutes; convert to seconds.
    minutes = random.gauss(5.0, 5.0)
    minutes = min(9.0, max(1.0, minutes))
    seconds = int(round(minutes * 60.0))
    # enforce bounds after rounding
    return min(540, max(60, seconds))


def choose_destination(origin: int) -> int:
    return random.choice([s for s in STATIONS.keys() if s != origin])


def passenger_generator_process(
    env: simpy.Environment,
    station: Station,
    emitter: JsonlEmitter,
    passenger_counters: Dict[str, int],
):
    """Generate passengers for a single station.

    Passenger numbering is global-per-scenario in the PR: passenger_num is a
    sequential counter (with 0 reserved for the special initialization passenger).
    We implement this as a shared counter across all station generators.
    """

    # Special initialization passenger at t=0.5 seconds
    yield env.timeout(0.5)
    dest = choose_destination(station.station_id)
    p0 = Passenger(passenger_id=0, passenger_num=0, origin=station.station_id, destination=dest)
    emitter.emit(
        sim_time=env.now,
        event="passenger_generated",
        entity_type="passenger_generator",
        station_id=station.station_id,
        payload=p0.payload(),
    )
    station.enqueue(p0)

    while True:
        interval_s = sample_generation_interval_seconds()
        yield env.timeout(interval_s)

        passenger_counters["next"] += 1
        passenger_num = passenger_counters["next"]

        dest = choose_destination(station.station_id)
        passenger_id = passenger_num * 100 + station.station_id * 10 + dest
        p = Passenger(
            passenger_id=passenger_id,
            passenger_num=passenger_num,
            origin=station.station_id,
            destination=dest,
        )
        emitter.emit(
            sim_time=env.now,
            event="passenger_generated",
            entity_type="passenger_generator",
            station_id=station.station_id,
            payload=p.payload(),
        )
        station.enqueue(p)


def train_process(
    env: simpy.Environment,
    stations: Dict[int, Station],
    train: Train,
    emitter: JsonlEmitter,
):
    # Bayview(1,0) -> Carling -> Carleton -> Confed -> Greenboro(5,1) -> ... -> Bayview
    route: List[Tuple[int, int]] = [
        (1, 0),
        (2, 0),
        (3, 0),
        (4, 0),
        (5, 1),
        (4, 1),
        (3, 1),
        (2, 1),
    ]

    idx = 0
    while True:
        station_id, direction = route[idx]

        # Train arrival event at this stop
        emitter.emit(
            sim_time=env.now,
            event="train_arrival",
            entity_type="train",
            station_id=station_id,
            payload={"station": station_id, "direction": direction},
        )

        # Exiting: passengers alight one by one, starting 0.025s after arrival
        for p in train.pop_alighting(station_id):
            yield env.timeout(0.025)
            emitter.emit(
                sim_time=env.now,
                event="passenger_exiting",
                entity_type="train_queue",
                station_id=station_id,
                payload=p.payload(),
            )

        # Boarding: passengers board FIFO one by one, starting 0.025s after arrival or last exit
        station = stations[station_id]
        while station.queue:
            p = station.queue.popleft()
            yield env.timeout(0.025)
            train.board(p)
            emitter.emit(
                sim_time=env.now,
                event="passenger_boarding",
                entity_type="station_queue",
                station_id=station_id,
                payload=p.payload(),
            )

        # Travel interval: exactly 225 seconds between consecutive stops
        idx = (idx + 1) % len(route)
        yield env.timeout(225.0)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="O-Train Light Rail Simulation")
    p.add_argument(
        "--simulate_time",
        type=str,
        default="00:01:00:000",
        help='Simulation duration in "HH:MM:SS:mmm". Default: 00:01:00:000',
    )
    return p


def main(argv: Optional[List[str]] = None) -> int:
    # All logs to stderr.
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(message)s",
        stream=sys.stderr,
    )
    log = logging.getLogger("otrain")

    args = build_arg_parser().parse_args(argv)
    simulate_seconds = parse_simulate_time(args.simulate_time)

    # Seed RNG from system time.
    seed = time.time_ns()
    random.seed(seed)
    log.info("seed=%s", seed)

    env = simpy.Environment()
    emitter = JsonlEmitter(sys.stdout)

    stations = {sid: Station(sid) for sid in sorted(STATIONS.keys())}
    train = Train()

    # Global passenger counter shared by all generators (0 reserved for initialization passenger).
    passenger_counters: Dict[str, int] = {"next": 0}

    for sid in sorted(stations.keys()):
        env.process(passenger_generator_process(env, stations[sid], emitter, passenger_counters))

    env.process(train_process(env, stations, train, emitter))

    # Ensure the simulation terminates within 10 seconds of real time.
    start_wall = time.perf_counter()
    wall_limit_s = 9.5
    until = float(simulate_seconds)

    try:
        # Step the environment to preserve a wall-clock cutoff, but do not
        # advance simulation time past the requested `until`.
        while True:
            next_t = env.peek()  # time of next scheduled event (or inf)
            if next_t > until:
                break
            if time.perf_counter() - start_wall > wall_limit_s:
                log.warning(
                    "Stopping early due to wall-clock limit (sim_time=%.3f, requested=%.3f)",
                    env.now,
                    until,
                )
                break
            env.step()
    except simpy.core.EmptySchedule:
        # No more events to process.
        pass
    except Exception:
        log.exception("Simulation error")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
