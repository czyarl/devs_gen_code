#!/usr/bin/env python3
import argparse
import sys
import json
import logging
import random
import time
from collections import deque
import simpy  # type: ignore


STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro",
}


def parse_hhmmssmmm(s: str) -> float:
    parts = s.strip().split(":")
    if len(parts) != 4:
        raise ValueError("simulate_time must be in HH:MM:SS:mmm format")
    hh, mm, ss, mmm = parts
    h = int(hh)
    m = int(mm)
    sec = int(ss)
    ms = int(mmm)
    if h < 0 or m < 0 or sec < 0 or ms < 0:
        raise ValueError("simulate_time must be non-negative")
    return h * 3600.0 + m * 60.0 + sec + (ms / 1000.0)


def desired_direction(origin: int, destination: int) -> int:
    # 0=Southbound (1->5 increasing), 1=Northbound (5->1 decreasing)
    return 0 if destination > origin else 1


class EventSink:
    def __init__(self, out_stream, logger: logging.Logger):
        self.out = out_stream
        self.logger = logger

    def emit(self, sim_time: float, event: str, entity_type: str, station_id: int, payload: dict):
        obj = {
            "time": round(float(sim_time), 3),
            "event": event,
            "entity_type": entity_type,
            "station_id": int(station_id),
            "station": STATIONS[int(station_id)],
            "payload": payload,
        }
        self.out.write(json.dumps(obj) + "\n")


class Train:
    def __init__(self, env: simpy.Environment, sink: EventSink):
        self.env = env
        self.sink = sink
        self.onboard_by_dest = {sid: deque() for sid in STATIONS.keys()}

        # Repeating route: (station_id, direction)
        self.route = [
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
        self.route_idx = 0

    def add_passenger(self, p: dict):
        self.onboard_by_dest[p["destination"]].append(p)

    def process_alighting(self, station_id: int):
        q = self.onboard_by_dest[station_id]
        if not q:
            return
        yield self.env.timeout(0.025)
        while q:
            p = q.popleft()
            self.sink.emit(
                self.env.now,
                "passenger_exiting",
                "train_queue",
                station_id,
                {
                    "passenger_id": p["passenger_id"],
                    "passenger_num": p["passenger_num"],
                    "origin": p["origin"],
                    "destination": p["destination"],
                },
            )
            if q:
                yield self.env.timeout(0.025)

    def run(self, stations: dict):
        # Initial arrival at t=0.0 at Bayview (1, dir=0)
        while True:
            station_id, direction = self.route[self.route_idx]
            # Train arrival event
            self.sink.emit(
                self.env.now,
                "train_arrival",
                "train",
                station_id,
                {"station": station_id, "direction": direction},
            )

            # Trigger alighting + boarding (separate serial processes)
            self.env.process(self.process_alighting(station_id))
            self.env.process(stations[station_id].process_boarding(self, direction))

            # Travel to next stop
            yield self.env.timeout(225.0)
            self.route_idx = (self.route_idx + 1) % len(self.route)


class Station:
    def __init__(self, env: simpy.Environment, station_id: int, sink: EventSink):
        self.env = env
        self.station_id = station_id
        self.name = STATIONS[station_id]
        self.sink = sink
        self.queue = deque()
        self.passenger_counter = 0  # per-station counter; 0 reserved for initialization passenger

    def enqueue_passenger(self, p: dict):
        # Validation: origin must match station and destination different
        if p["origin"] != self.station_id:
            return
        if p["destination"] == self.station_id:
            return
        self.queue.append(p)

    def generate_passengers(self):
        # Initialization passenger at t=0.5
        yield self.env.timeout(0.5)
        dest_choices = [sid for sid in STATIONS.keys() if sid != self.station_id]
        init_dest = random.choice(dest_choices)
        init_p = {
            "passenger_id": 0,
            "passenger_num": 0,
            "origin": self.station_id,
            "destination": init_dest,
        }
        self.sink.emit(
            self.env.now,
            "passenger_generated",
            "passenger_generator",
            self.station_id,
            dict(init_p),
        )
        self.enqueue_passenger(init_p)

        # Subsequent passengers
        while True:
            # Normal distribution in minutes (mean=5.0, std=5.0), clamped to [1,9] minutes
            minutes = random.gauss(5.0, 5.0)
            if minutes < 1.0:
                minutes = 1.0
            elif minutes > 9.0:
                minutes = 9.0
            dt = int(round(minutes * 60.0))
            if dt < 1:
                dt = 1
            yield self.env.timeout(float(dt))

            self.passenger_counter += 1
            dest = random.choice(dest_choices)
            pid = self.passenger_counter * 100 + self.station_id * 10 + dest
            p = {
                "passenger_id": pid,
                "passenger_num": self.passenger_counter,
                "origin": self.station_id,
                "destination": dest,
            }
            self.sink.emit(
                self.env.now,
                "passenger_generated",
                "passenger_generator",
                self.station_id,
                dict(p),
            )
            self.enqueue_passenger(p)

    def process_boarding(self, train: Train, train_direction: int):
        # Strict FIFO: only board if the front passenger wants this direction; cannot skip.
        if not self.queue:
            return
        if desired_direction(self.queue[0]["origin"], self.queue[0]["destination"]) != train_direction:
            return

        yield self.env.timeout(0.025)
        while self.queue:
            p0 = self.queue[0]
            if desired_direction(p0["origin"], p0["destination"]) != train_direction:
                break
            p = self.queue.popleft()
            train.add_passenger(p)
            self.sink.emit(
                self.env.now,
                "passenger_boarding",
                "station_queue",
                self.station_id,
                {
                    "passenger_id": p["passenger_id"],
                    "passenger_num": p["passenger_num"],
                    "origin": p["origin"],
                    "destination": p["destination"],
                },
            )
            if self.queue:
                # Next passenger boards 0.025s after previous, but only if FIFO head matches direction
                pnext = self.queue[0]
                if desired_direction(pnext["origin"], pnext["destination"]) != train_direction:
                    break
                yield self.env.timeout(0.025)


def build_logger() -> logging.Logger:
    logger = logging.getLogger("o_train_sim")
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter("[%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.handlers = [handler]
    logger.propagate = False
    return logger


def main():
    parser = argparse.ArgumentParser(description="O-Train Light Rail Simulation (SimPy)")
    parser.add_argument("--simulate_time", type=str, default="00:01:00:000",
                        help='Simulation duration in "HH:MM:SS:mmm" (default: 00:01:00:000)')
    args = parser.parse_args()

    logger = build_logger()

    try:
        simulate_time = parse_hhmmssmmm(args.simulate_time)
    except Exception as e:
        logger.error(f"Invalid --simulate_time: {e}")
        sys.exit(2)

    # Seed RNG from system time (allowed for initialization only)
    seed = time.time_ns()
    random.seed(seed)
    logger.info(f"Random seed: {seed}")

    env = simpy.Environment()
    sink = EventSink(sys.stdout, logger)

    stations = {sid: Station(env, sid, sink) for sid in STATIONS.keys()}
    for st in stations.values():
        env.process(st.generate_passengers())

    train = Train(env, sink)
    env.process(train.run(stations))

    # Run with wall-clock safety (guarantee termination in <=10 seconds real time)
    wall_start = time.time()
    wall_deadline = wall_start + 9.5  # safety margin
    max_steps = 2_000_000

    steps = 0
    try:
        # Step-by-step execution to allow wall-clock cutoff
        while True:
            if steps >= max_steps:
                logger.warning("Stopping early: max simulation steps reached.")
                break
            if time.time() >= wall_deadline:
                logger.warning("Stopping early: wall-clock deadline reached.")
                break
            nxt = env.peek()
            if nxt == float("inf") or nxt > simulate_time:
                break
            env.step()
            steps += 1

        # If we stopped exactly because nxt>simulate_time, we are done.
        # If there are events at exactly simulate_time, allow them.
        if time.time() < wall_deadline and steps < max_steps:
            # Run all events scheduled at or before simulate_time
            env.run(until=simulate_time)
    except Exception as e:
        logger.error(f"Simulation error: {e}")
        raise


if __name__ == "__main__":
    main()