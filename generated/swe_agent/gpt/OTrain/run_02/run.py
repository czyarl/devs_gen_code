#!/usr/bin/env python3
"""Ottawa O-Train Light Rail DES simulation.

Entry point: python run.py

Stdout: JSONL events only.
Stderr: logs/debug.
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


def parse_simulate_time(value: str) -> float:
    """Parse HH:MM:SS:mmm into seconds (float)."""
    try:
        hh, mm, ss, mmm = value.split(":")
        hours = int(hh)
        minutes = int(mm)
        seconds = int(ss)
        millis = int(mmm)
    except Exception as e:  # noqa: BLE001
        raise argparse.ArgumentTypeError(
            "--simulate_time must be in format HH:MM:SS:mmm"
        ) from e

    if hours < 0 or minutes < 0 or seconds < 0 or millis < 0:
        raise argparse.ArgumentTypeError("--simulate_time must be non-negative")
    if minutes >= 60 or seconds >= 60 or millis >= 1000:
        raise argparse.ArgumentTypeError("--simulate_time components out of range")

    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


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


class EventRecorder:
    """Collect events during the run and print them in deterministic order."""

    def __init__(self) -> None:
        self._events: List[dict] = []

    def record(
        self,
        *,
        time_s: float,
        event: str,
        entity_type: str,
        station_id: int,
        payload: dict,
    ) -> None:
        if station_id not in STATIONS:
            raise ValueError(f"invalid station_id {station_id}")

        # Keep millisecond precision.
        time_s = round(float(time_s), 3)

        self._events.append(
            {
                "time": time_s,
                "event": event,
                "entity_type": entity_type,
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": payload,
            }
        )

    def dump_jsonl(self, fp) -> None:
        # Deterministic order for events at the same timestamp.
        priority = {
            "passenger_generated": 0,
            "train_arrival": 1,
            "passenger_exiting": 2,
            "passenger_boarding": 3,
        }
        self._events.sort(key=lambda e: (e["time"], priority.get(e["event"], 99)))
        for e in self._events:
            fp.write(json.dumps(e) + "\n")


class PassengerCounter:
    def __init__(self) -> None:
        self._n = 0

    def next(self) -> int:
        self._n += 1
        return self._n


class StationQueue:
    def __init__(self, station_id: int) -> None:
        self.station_id = station_id
        self._q: Deque[Passenger] = deque()

    def put(self, p: Passenger) -> None:
        # Validation: encoded origin must match station and destination differs.
        if p.origin != self.station_id:
            return
        if p.destination == p.origin:
            return
        self._q.append(p)

    def get(self) -> Optional[Passenger]:
        if not self._q:
            return None
        return self._q.popleft()

    def __len__(self) -> int:
        return len(self._q)


class Train:
    def __init__(
        self,
        env: simpy.Environment,
        recorder: EventRecorder,
        station_queues: Dict[int, StationQueue],
    ) -> None:
        self.env = env
        self.recorder = recorder
        self.station_queues = station_queues
        self._by_dest: Dict[int, Deque[Passenger]] = {sid: deque() for sid in STATIONS}

    def arrive(self, station_id: int, direction: int) -> None:
        self.recorder.record(
            time_s=self.env.now,
            event="train_arrival",
            entity_type="train",
            station_id=station_id,
            payload={"station": station_id, "direction": direction},
        )

        # Alighting and boarding are modeled as independent serial processes
        # starting 0.025s after arrival.
        self.env.process(self._handle_alighting(station_id))
        self.env.process(self._handle_boarding(station_id))

    def _handle_alighting(self, station_id: int):
        q = self._by_dest.get(station_id)
        if not q:
            return
        while q:
            yield self.env.timeout(0.025)
            p = q.popleft()
            self.recorder.record(
                time_s=self.env.now,
                event="passenger_exiting",
                entity_type="train_queue",
                station_id=station_id,
                payload=p.payload(),
            )

    def _handle_boarding(self, station_id: int):
        sq = self.station_queues[station_id]
        while len(sq) > 0:
            yield self.env.timeout(0.025)
            p = sq.get()
            if p is None:
                return
            self._by_dest[p.destination].append(p)
            self.recorder.record(
                time_s=self.env.now,
                event="passenger_boarding",
                entity_type="station_queue",
                station_id=station_id,
                payload=p.payload(),
            )


def passenger_generator(
    env: simpy.Environment,
    *,
    station_id: int,
    recorder: EventRecorder,
    station_queue: StationQueue,
    counter: PassengerCounter,
):
    # Initialization passenger at t=0.5
    yield env.timeout(0.5)
    init_dest = random.choice([sid for sid in STATIONS if sid != station_id])
    init_p = Passenger(
        passenger_id=0, passenger_num=0, origin=station_id, destination=init_dest
    )
    recorder.record(
        time_s=env.now,
        event="passenger_generated",
        entity_type="passenger_generator",
        station_id=station_id,
        payload=init_p.payload(),
    )
    station_queue.put(init_p)

    while True:
        # Randomized interval: Normal(5,5) minutes, clamped to [1,9] minutes.
        minutes = clamp(random.gauss(5.0, 5.0), 1.0, 9.0)
        seconds = int(round(minutes * 60.0))
        yield env.timeout(seconds)

        dest = random.choice([sid for sid in STATIONS if sid != station_id])
        passenger_num = counter.next()
        passenger_id = passenger_num * 100 + station_id * 10 + dest
        p = Passenger(
            passenger_id=passenger_id,
            passenger_num=passenger_num,
            origin=station_id,
            destination=dest,
        )
        recorder.record(
            time_s=env.now,
            event="passenger_generated",
            entity_type="passenger_generator",
            station_id=station_id,
            payload=p.payload(),
        )
        station_queue.put(p)


def train_scheduler(env: simpy.Environment, *, train: Train):
    # Route sequence (station_id, direction)
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
    # Initial arrival at t=0 at Bayview (1, dir=0)
    station_id, direction = route[idx]
    train.arrive(station_id, direction)

    while True:
        yield env.timeout(225)
        idx = (idx + 1) % len(route)
        station_id, direction = route[idx]
        train.arrive(station_id, direction)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="O-Train Light Rail DES simulation")
    p.add_argument(
        "--simulate_time",
        type=str,
        default="00:01:00:000",
        help='Simulation duration in format "HH:MM:SS:mmm"',
    )
    return p


def run_with_wall_clock_limit(
    env: simpy.Environment,
    *,
    until: float,
    max_wall_seconds: float = 9.0,
) -> None:
    """Run a SimPy environment, but ensure it finishes quickly in real time.

    Simulation logic remains purely based on simulation time; the wall-clock
    limit is only a safety guard to prevent pathological runs.
    """

    start = time.monotonic()
    while True:
        if time.monotonic() - start > max_wall_seconds:
            logging.warning("Wall-clock limit reached; stopping simulation early")
            break

        nxt = env.peek()
        # No more events to process.
        if nxt == float("inf"):
            break
        # Stop once the next event would be after the desired horizon.
        if nxt > until:
            # Advance time to the requested horizon (matches env.run semantics).
            env._now = until  # type: ignore[attr-defined]  # SimPy internal
            break

        env.step()


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)

    args = build_arg_parser().parse_args(argv)
    simulate_seconds = parse_simulate_time(args.simulate_time)

    # Seed RNG with system time.
    random.seed(time.time_ns())

    env = simpy.Environment()
    recorder = EventRecorder()
    counter = PassengerCounter()

    station_queues = {sid: StationQueue(sid) for sid in STATIONS}
    train = Train(env, recorder, station_queues)

    # Launch passenger generators for each station.
    for sid in STATIONS:
        env.process(
            passenger_generator(
                env,
                station_id=sid,
                recorder=recorder,
                station_queue=station_queues[sid],
                counter=counter,
            )
        )

    # Launch train scheduler.
    env.process(train_scheduler(env, train=train))

    # Run DES.
    run_with_wall_clock_limit(env, until=simulate_seconds)

    # Emit JSONL to stdout only.
    recorder.dump_jsonl(sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
