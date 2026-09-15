#!/usr/bin/env python3
"""O-Train Light Rail DES simulation (SimPy).

Outputs JSONL events to stdout. Logs/debug go to stderr.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import time
from collections import deque

import simpy


STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro",
}

# Route stops with direction at the stop.
# 0 = Southbound (Bayview -> Greenboro)
# 1 = Northbound (Greenboro -> Bayview)
ROUTE = [
    (1, 0),
    (2, 0),
    (3, 0),
    (4, 0),
    (5, 1),
    (4, 1),
    (3, 1),
    (2, 1),
]

TRAVEL_INTERVAL_S = 225
SERIAL_STEP_S = 0.025


def parse_hhmmssmmm(value: str) -> float:
    """Parse HH:MM:SS:mmm into seconds (float)."""
    parts = value.strip().split(":")
    if len(parts) != 4:
        raise ValueError("simulate_time must be in HH:MM:SS:mmm")
    hh, mm, ss, mmm = parts
    try:
        hh_i = int(hh)
        mm_i = int(mm)
        ss_i = int(ss)
        mmm_i = int(mmm)
    except ValueError as e:
        raise ValueError("simulate_time fields must be integers") from e
    if hh_i < 0 or mm_i < 0 or ss_i < 0 or mmm_i < 0:
        raise ValueError("simulate_time fields must be non-negative")
    if mm_i >= 60 or ss_i >= 60 or mmm_i >= 1000:
        raise ValueError("simulate_time must satisfy MM<60, SS<60, mmm<1000")
    return hh_i * 3600.0 + mm_i * 60.0 + ss_i + (mmm_i / 1000.0)


class EventEmitter:
    def __init__(self, wall_limit_s: float = 9.5):
        self.wall_limit_s = float(wall_limit_s)
        self.wall_start = time.perf_counter()
        self.event_count = 0

    @staticmethod
    def _t(env: simpy.Environment) -> float:
        # Millisecond precision.
        return round(float(env.now), 3)

    def emit(self, env: simpy.Environment, *, event: str, entity_type: str, station_id: int, payload: dict) -> None:
        """Emit a single JSONL event to stdout.

        Any non-event output MUST go to stderr, so this method never logs.
        """
        # Kill switch to guarantee we end fast in real time.
        if (time.perf_counter() - self.wall_start) > self.wall_limit_s:
            logging.warning("Wall-time limit reached; stopping simulation early")
            # StopSimulation must carry a value for SimPy's env.run() return path.
            raise simpy.core.StopSimulation("wall_time_limit")

        self.event_count += 1
        obj = {
            "time": self._t(env),
            "event": event,
            "entity_type": entity_type,
            "station_id": int(station_id),
            "station": STATIONS[int(station_id)],
            "payload": payload,
        }
        try:
            sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
        except BrokenPipeError:
            # Downstream closed the pipe (e.g., piping into `head`). Stop cleanly.
            raise simpy.core.StopSimulation("broken_pipe")  # handled by env.run


class Train:
    def __init__(self, emitter: EventEmitter):
        self.emitter = emitter
        # destination_station_id -> deque([passenger_dict, ...])
        self.onboard: dict[int, deque] = {}

    def board(self, passenger: dict) -> None:
        dest = int(passenger["destination"])
        self.onboard.setdefault(dest, deque()).append(passenger)

    def alight_process(self, env: simpy.Environment, station_id: int):
        dq = self.onboard.get(int(station_id))
        if not dq:
            return

        # First passenger alights SERIAL_STEP_S after arrival.
        yield env.timeout(SERIAL_STEP_S)
        while dq:
            passenger = dq.popleft()
            self.emitter.emit(
                env,
                event="passenger_exiting",
                entity_type="train_queue",
                station_id=station_id,
                payload={
                    "passenger_id": int(passenger["passenger_id"]),
                    "passenger_num": int(passenger["passenger_num"]),
                    "origin": int(passenger["origin"]),
                    "destination": int(passenger["destination"]),
                },
            )
            if dq:
                yield env.timeout(SERIAL_STEP_S)

        # Clean up empty bucket
        self.onboard.pop(int(station_id), None)


class Station:
    def __init__(self, station_id: int, emitter: EventEmitter):
        self.station_id = int(station_id)
        self.emitter = emitter
        self.queue: deque[dict] = deque()
        self.passenger_num = 0  # 0 reserved for initialization passenger

    def _random_destination(self) -> int:
        choices = [sid for sid in STATIONS.keys() if sid != self.station_id]
        return int(random.choice(choices))

    def passenger_generator_process(self, env: simpy.Environment, end_time: float):
        # Initialization passenger at t=0.5
        yield env.timeout(0.5)
        if env.now > end_time:
            return

        init_dest = self._random_destination()
        init_passenger = {
            "passenger_id": 0,
            "passenger_num": 0,
            "origin": self.station_id,
            "destination": init_dest,
        }
        self.emitter.emit(
            env,
            event="passenger_generated",
            entity_type="passenger_generator",
            station_id=self.station_id,
            payload=dict(init_passenger),
        )
        self.queue.append(init_passenger)

        # Subsequent passengers
        while True:
            # Normal in minutes, clamp to [1, 9], convert to seconds and round.
            interval_min = random.gauss(5.0, 5.0)
            interval_min = max(1.0, min(9.0, interval_min))
            interval_s = int(round(interval_min * 60.0))
            yield env.timeout(interval_s)
            if env.now > end_time:
                return

            self.passenger_num += 1
            dest = self._random_destination()
            passenger_id = self.passenger_num * 100 + self.station_id * 10 + dest
            passenger = {
                "passenger_id": int(passenger_id),
                "passenger_num": int(self.passenger_num),
                "origin": int(self.station_id),
                "destination": int(dest),
            }

            # Validation: encoded origin must match, destination must differ.
            if passenger["origin"] != self.station_id or passenger["destination"] == self.station_id:
                continue

            self.emitter.emit(
                env,
                event="passenger_generated",
                entity_type="passenger_generator",
                station_id=self.station_id,
                payload=dict(passenger),
            )
            self.queue.append(passenger)

    def boarding_process(self, env: simpy.Environment, train: Train):
        if not self.queue:
            return

        # First boarding SERIAL_STEP_S after arrival.
        yield env.timeout(SERIAL_STEP_S)

        while self.queue:
            passenger = self.queue.popleft()
            # Validation: origin must match this station and destination differs.
            if int(passenger["origin"]) != self.station_id or int(passenger["destination"]) == self.station_id:
                continue

            self.emitter.emit(
                env,
                event="passenger_boarding",
                entity_type="station_queue",
                station_id=self.station_id,
                payload={
                    "passenger_id": int(passenger["passenger_id"]),
                    "passenger_num": int(passenger["passenger_num"]),
                    "origin": int(passenger["origin"]),
                    "destination": int(passenger["destination"]),
                },
            )
            train.board(passenger)

            if self.queue:
                yield env.timeout(SERIAL_STEP_S)


def train_scheduler_process(env: simpy.Environment, train: Train, stations: dict[int, Station], end_time: float):
    idx = 0

    # Initial arrival at t=0.0 at Bayview (Station 1, Direction 0)
    station_id, direction = ROUTE[idx]
    train.emitter.emit(
        env,
        event="train_arrival",
        entity_type="train",
        station_id=station_id,
        payload={"station": int(station_id), "direction": int(direction)},
    )
    env.process(train.alight_process(env, station_id))
    env.process(stations[station_id].boarding_process(env, train))

    while True:
        yield env.timeout(TRAVEL_INTERVAL_S)
        if env.now > end_time + TRAVEL_INTERVAL_S:
            # No need to keep scheduling far beyond the requested horizon.
            return

        idx = (idx + 1) % len(ROUTE)
        station_id, direction = ROUTE[idx]

        train.emitter.emit(
            env,
            event="train_arrival",
            entity_type="train",
            station_id=station_id,
            payload={"station": int(station_id), "direction": int(direction)},
        )

        # Trigger alighting and boarding at this stop.
        env.process(train.alight_process(env, station_id))
        env.process(stations[station_id].boarding_process(env, train))


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="O-Train Light Rail Simulation (DES)")
    p.add_argument(
        "--simulate_time",
        type=str,
        default="00:01:00:000",
        help='Simulation duration as "HH:MM:SS:mmm" (default: 00:01:00:000).',
    )
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s:%(message)s")

    args = build_arg_parser().parse_args(argv)
    try:
        end_time = parse_hhmmssmmm(args.simulate_time)
    except ValueError as e:
        logging.error(str(e))
        return 2

    # Seed RNG with system time.
    seed = time.time_ns()
    random.seed(seed)
    logging.info("seed=%s end_time_s=%s", seed, end_time)

    emitter = EventEmitter(wall_limit_s=9.5)
    env = simpy.Environment()

    stations: dict[int, Station] = {sid: Station(sid, emitter) for sid in STATIONS}
    train = Train(emitter)

    # Start passenger generation processes.
    for st in stations.values():
        env.process(st.passenger_generator_process(env, end_time=end_time))

    # Start train scheduler.
    env.process(train_scheduler_process(env, train, stations, end_time=end_time))

    try:
        env.run(until=end_time)
    except simpy.core.StopSimulation:
        # Early stop (wall-time kill switch or broken pipe). Not an error.
        return 0
    except BrokenPipeError:
        # Extra safety: in case a BrokenPipeError escapes.
        return 0
    except Exception:
        logging.exception("Simulation error")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
