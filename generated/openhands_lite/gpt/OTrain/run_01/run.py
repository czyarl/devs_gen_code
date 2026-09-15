import argparse
import json
import logging
import random
import sys
import time
from collections import defaultdict, deque

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
]

TRAVEL_INTERVAL_S = 225
SERIAL_STEP_S = 0.025


def parse_hhmmssmmm(value: str) -> float:
    parts = value.split(":")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("Expected HH:MM:SS:mmm")
    try:
        hh = int(parts[0])
        mm = int(parts[1])
        ss = int(parts[2])
        mmm = int(parts[3])
    except ValueError as e:
        raise argparse.ArgumentTypeError("Non-integer time component") from e

    if hh < 0 or not (0 <= mm <= 59) or not (0 <= ss <= 59) or not (0 <= mmm <= 999):
        raise argparse.ArgumentTypeError("Out-of-range time component")

    return hh * 3600 + mm * 60 + ss + (mmm / 1000.0)


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


class EventSink:
    def __init__(self, env: simpy.Environment):
        self.env = env

    def emit(self, event: str, entity_type: str, station_id: int, payload: dict) -> None:
        obj = {
            "time": round(float(self.env.now), 3),
            "event": event,
            "entity_type": entity_type,
            "station_id": int(station_id),
            "station": STATIONS[int(station_id)],
            "payload": payload,
        }
        sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")


class Station:
    def __init__(self, station_id: int):
        self.station_id = station_id
        self.queue: deque[dict] = deque()

    def maybe_enqueue(self, p: dict) -> bool:
        origin = int(p.get("origin"))
        destination = int(p.get("destination"))
        passenger_id = int(p.get("passenger_id"))

        if destination == origin:
            return False
        if origin != self.station_id:
            return False

        # Validation against encoded origin/destination for non-initial passengers.
        if passenger_id != 0:
            enc = passenger_id % 100
            enc_origin = enc // 10
            enc_dest = enc % 10
            if enc_origin != origin or enc_dest != destination:
                return False

        self.queue.append(p)
        return True


class Train:
    def __init__(self):
        self.by_destination: dict[int, deque[dict]] = defaultdict(deque)

    def add_passenger(self, p: dict) -> None:
        self.by_destination[int(p["destination"])].append(p)

    def pop_all_for_station(self, station_id: int) -> list[dict]:
        dq = self.by_destination.get(int(station_id))
        if not dq:
            return []
        passengers = list(dq)
        dq.clear()
        return passengers


def choose_destination(origin: int) -> int:
    choices = [sid for sid in STATIONS.keys() if sid != origin]
    return random.choice(choices)


def passenger_generator(env: simpy.Environment, sink: EventSink, station: Station) -> None:
    passenger_num = 0

    def make_passenger(initial: bool) -> dict:
        nonlocal passenger_num
        origin = station.station_id
        destination = choose_destination(origin)
        if initial:
            passenger_id = 0
            passenger_num = 0
        else:
            passenger_num += 1
            passenger_id = passenger_num * 100 + origin * 10 + destination
        return {
            "passenger_id": int(passenger_id),
            "passenger_num": int(passenger_num),
            "origin": int(origin),
            "destination": int(destination),
        }

    yield env.timeout(0.5)
    p0 = make_passenger(initial=True)
    sink.emit(
        event="passenger_generated",
        entity_type="passenger_generator",
        station_id=station.station_id,
        payload=p0,
    )
    station.maybe_enqueue(p0)

    while True:
        interval_min = random.normalvariate(5.0, 5.0)
        interval_min = clamp(interval_min, 1.0, 9.0)
        interval_s = int(round(interval_min * 60.0))
        yield env.timeout(interval_s)

        p = make_passenger(initial=False)
        sink.emit(
            event="passenger_generated",
            entity_type="passenger_generator",
            station_id=station.station_id,
            payload=p,
        )
        station.maybe_enqueue(p)


def process_exiting(env: simpy.Environment, sink: EventSink, station_id: int, exiting: list[dict]) -> simpy.events.Event:
    if not exiting:
        return env.timeout(0)

    def _proc() -> None:
        for i, p in enumerate(exiting):
            yield env.timeout(SERIAL_STEP_S if i == 0 else SERIAL_STEP_S)
            sink.emit(
                event="passenger_exiting",
                entity_type="train_queue",
                station_id=station_id,
                payload=p,
            )

    return env.process(_proc())


def process_boarding(
    env: simpy.Environment,
    sink: EventSink,
    station: Station,
    train: Train,
    boarding: list[dict],
) -> simpy.events.Event:
    if not boarding:
        return env.timeout(0)

    def _proc() -> None:
        for i, p in enumerate(boarding):
            yield env.timeout(SERIAL_STEP_S if i == 0 else SERIAL_STEP_S)
            train.add_passenger(p)
            sink.emit(
                event="passenger_boarding",
                entity_type="station_queue",
                station_id=station.station_id,
                payload=p,
            )

    return env.process(_proc())


def train_scheduler(env: simpy.Environment, sink: EventSink, stations: dict[int, Station], train: Train) -> None:
    idx = 0
    while True:
        station_id, direction = ROUTE[idx]
        sink.emit(
            event="train_arrival",
            entity_type="train",
            station_id=station_id,
            payload={"station": int(station_id), "direction": int(direction)},
        )

        exiting_list = train.pop_all_for_station(station_id)

        station = stations[station_id]
        boarding_list = list(station.queue)
        station.queue.clear()

        exiting_proc = process_exiting(env, sink, station_id, exiting_list)
        boarding_proc = process_boarding(env, sink, station, train, boarding_list)
        yield simpy.events.AllOf(env, [exiting_proc, boarding_proc])

        yield env.timeout(TRAVEL_INTERVAL_S)
        idx = (idx + 1) % len(ROUTE)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--simulate_time",
        type=parse_hhmmssmmm,
        default=parse_hhmmssmmm("00:01:00:000"),
        help='Simulation duration as "HH:MM:SS:mmm"',
    )
    args = parser.parse_args(argv)

    random.seed(time.time_ns())

    logging.basicConfig(stream=sys.stderr, level=logging.INFO)

    env = simpy.Environment()
    sink = EventSink(env)

    stations = {sid: Station(sid) for sid in STATIONS.keys()}
    for st in stations.values():
        env.process(passenger_generator(env, sink, st))

    train = Train()
    env.process(train_scheduler(env, sink, stations, train))

    sim_time = float(args.simulate_time)
    if sim_time < 0:
        sim_time = 0.0

    # Safety: enforce a hard wall-clock cutoff (no real-time simulation).
    start_wall = time.perf_counter()
    deadline = start_wall + 9.5

    try:
        while True:
            if time.perf_counter() > deadline:
                logging.warning("Wall-clock cutoff reached; stopping simulation early")
                break

            next_t = env.peek()
            if next_t == float("inf") or next_t >= sim_time:
                env.run(until=sim_time)
                break

            env.step()
    except simpy.core.StopSimulation:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
