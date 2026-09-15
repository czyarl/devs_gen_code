#!/usr/bin/env python3
import argparse
import json
import logging
import random
import sys
import time
from collections import defaultdict, deque

import simpy

# Only standard library + simpy are used; xdevs is allowed but unnecessary.



STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro",
}


def parse_simulate_time(value: str) -> float:
    # Expected format: HH:MM:SS:mmm
    parts = value.strip().split(":")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("simulate_time must be HH:MM:SS:mmm")
    try:
        hh = int(parts[0])
        mm = int(parts[1])
        ss = int(parts[2])
        mmm = int(parts[3])
    except ValueError as e:
        raise argparse.ArgumentTypeError("simulate_time must be numeric HH:MM:SS:mmm") from e

    if hh < 0 or mm < 0 or ss < 0 or mmm < 0:
        raise argparse.ArgumentTypeError("simulate_time components must be non-negative")
    if mm >= 60 or ss >= 60 or mmm >= 1000:
        raise argparse.ArgumentTypeError("simulate_time must satisfy MM<60, SS<60, mmm<1000")

    return float(hh * 3600 + mm * 60 + ss) + (mmm / 1000.0)


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class EventSink:
    def __init__(self) -> None:
        self._out = sys.stdout

    @staticmethod
    def _t(t: float) -> float:
        # milliseconds precision
        return round(t + 1e-12, 3)

    def emit(self, *, t: float, event: str, entity_type: str, station_id: int, payload: dict) -> None:
        obj = {
            "time": self._t(t),
            "event": event,
            "entity_type": entity_type,
            "station_id": int(station_id),
            "station": STATIONS[int(station_id)],
            "payload": payload,
        }
        self._out.write(json.dumps(obj) + "\n")


def make_passenger(*, passenger_id: int, passenger_num: int, origin: int, destination: int) -> dict:
    return {
        "passenger_id": int(passenger_id),
        "passenger_num": int(passenger_num),
        "origin": int(origin),
        "destination": int(destination),
    }


def passenger_generator(
    env: simpy.Environment,
    station_id: int,
    station_queue: deque,
    sink: EventSink,
    logger: logging.Logger,
):
    origin = int(station_id)

    # Initialization passenger
    yield env.timeout(0.5)
    init_dest = random.choice([s for s in STATIONS.keys() if s != origin])
    p0 = make_passenger(passenger_id=0, passenger_num=0, origin=origin, destination=init_dest)
    station_queue.append(p0)
    sink.emit(
        t=env.now,
        event="passenger_generated",
        entity_type="passenger_generator",
        station_id=origin,
        payload=p0,
    )

    passenger_num = 0
    while True:
        # Normal(mean=5min, std=5min), clamped to [1,9] minutes.
        interval_min = clamp(random.gauss(5.0, 5.0), 1.0, 9.0)
        interval_s = int(round(interval_min * 60.0))
        yield env.timeout(interval_s)

        passenger_num += 1
        dest = random.choice([s for s in STATIONS.keys() if s != origin])
        passenger_id = passenger_num * 100 + origin * 10 + dest
        p = make_passenger(
            passenger_id=passenger_id,
            passenger_num=passenger_num,
            origin=origin,
            destination=dest,
        )

        if p["origin"] != origin or p["destination"] == origin:
            logger.warning("Invalid passenger generated; dropping: %s", p)
            continue

        station_queue.append(p)
        sink.emit(
            t=env.now,
            event="passenger_generated",
            entity_type="passenger_generator",
            station_id=origin,
            payload=p,
        )


def alight_process(
    env: simpy.Environment,
    station_id: int,
    onboard_by_dest: dict,
    sink: EventSink,
):
    q = onboard_by_dest.get(int(station_id))
    if not q:
        yield env.timeout(0)
        return

    yield env.timeout(0.025)
    while q:
        p = q.popleft()
        sink.emit(
            t=env.now,
            event="passenger_exiting",
            entity_type="train_queue",
            station_id=int(station_id),
            payload=p,
        )
        if q:
            yield env.timeout(0.025)


def board_process(
    env: simpy.Environment,
    station_id: int,
    station_queue: deque,
    onboard_by_dest: dict,
    sink: EventSink,
):
    n0 = len(station_queue)
    if n0 <= 0:
        yield env.timeout(0)
        return

    yield env.timeout(0.025)
    for i in range(n0):
        p = station_queue.popleft()
        onboard_by_dest[int(p["destination"])].append(p)
        sink.emit(
            t=env.now,
            event="passenger_boarding",
            entity_type="station_queue",
            station_id=int(station_id),
            payload=p,
        )
        if i != n0 - 1:
            yield env.timeout(0.025)


def train_process(
    env: simpy.Environment,
    station_queues: dict,
    sink: EventSink,
    logger: logging.Logger,
):
    # Repeating route per specification.
    route_cycle = [
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

    onboard_by_dest = defaultdict(deque)

    # Initial arrival at t=0.
    while True:
        station_id, direction = route_cycle[idx]
        arrival_t = env.now

        sink.emit(
            t=arrival_t,
            event="train_arrival",
            entity_type="train",
            station_id=int(station_id),
            payload={"station": int(station_id), "direction": int(direction)},
        )

        alight_ev = env.process(alight_process(env, station_id, onboard_by_dest, sink))
        board_ev = env.process(
            board_process(env, station_id, station_queues[int(station_id)], onboard_by_dest, sink)
        )
        yield alight_ev & board_ev

        # Maintain exactly 225s between consecutive arrival events.
        dwell = env.now - arrival_t
        remaining = 225.0 - dwell
        if remaining < 0:
            logger.warning(
                "Dwell time %.3fs exceeded 225s interval at station %s", dwell, station_id
            )
            remaining = 0.0
        yield env.timeout(remaining)

        idx = (idx + 1) % len(route_cycle)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="O-Train light rail DES simulation")
    p.add_argument(
        "--simulate_time",
        type=str,
        default="00:01:00:000",
        help='Simulation duration as "HH:MM:SS:mmm" (default: 00:01:00:000)',
    )
    return p


def main(argv: list[str]) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(levelname)s: %(message)s")
    logger = logging.getLogger("otrain")

    seed = time.time_ns()
    random.seed(seed)
    logger.info("Seed: %s", seed)

    env = simpy.Environment()
    sink = EventSink()

    station_queues = {sid: deque() for sid in STATIONS.keys()}

    for sid in STATIONS.keys():
        env.process(passenger_generator(env, sid, station_queues[sid], sink, logger))

    env.process(train_process(env, station_queues, sink, logger))

    until = float(parse_simulate_time(args.simulate_time))
    max_wall_s = 9.5
    start_wall = time.perf_counter()

    # Manual stepping to guarantee real-time completion.
    while True:
        if time.perf_counter() - start_wall > max_wall_s:
            logger.warning("Wall-time limit reached; stopping simulation early")
            break
        nxt = env.peek()
        if nxt == float("inf") or nxt > until:
            break
        env.step()

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
