import argparse
import json
import logging
import random
import sys
import time
from collections import defaultdict, deque

import simpy

try:
    import xdevs  # noqa: F401
except Exception:  # pragma: no cover
    xdevs = None


STATION_NAMES = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro",
}


def parse_simulate_time(value: str) -> float:
    parts = value.split(":")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError(
            "simulate_time must be in format HH:MM:SS:mmm"
        )

    try:
        hh, mm, ss, mmm = (int(p) for p in parts)
    except ValueError as e:
        raise argparse.ArgumentTypeError(
            "simulate_time must contain only integers"
        ) from e

    if hh < 0 or mm < 0 or ss < 0 or mmm < 0:
        raise argparse.ArgumentTypeError("simulate_time components must be non-negative")
    if mm >= 60 or ss >= 60 or mmm >= 1000:
        raise argparse.ArgumentTypeError(
            "simulate_time must satisfy 0<=MM<60, 0<=SS<60, 0<=mmm<1000"
        )

    return hh * 3600.0 + mm * 60.0 + ss + mmm / 1000.0


def jsonl_emit(
    *,
    now: float,
    event: str,
    entity_type: str,
    station_id: int,
    payload: dict,
) -> None:
    obj = {
        "time": round(float(now), 3),
        "event": event,
        "entity_type": entity_type,
        "station_id": int(station_id),
        "station": STATION_NAMES[int(station_id)],
        "payload": payload,
    }
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def choose_destination(origin: int) -> int:
    options = [sid for sid in STATION_NAMES.keys() if sid != origin]
    return random.choice(options)


class Station:
    def __init__(self, station_id: int):
        self.station_id = int(station_id)
        self.queue = deque()
        self.passenger_num = 0

    def enqueue(self, passenger: dict) -> None:
        if passenger["origin"] != self.station_id:
            return
        if passenger["destination"] == self.station_id:
            return
        self.queue.append(passenger)

    def generate_passengers(self, env: simpy.Environment):
        yield env.timeout(0.5)
        init_dest = choose_destination(self.station_id)
        init_passenger = {
            "passenger_id": 0,
            "passenger_num": 0,
            "origin": self.station_id,
            "destination": init_dest,
        }
        jsonl_emit(
            now=env.now,
            event="passenger_generated",
            entity_type="passenger_generator",
            station_id=self.station_id,
            payload=dict(init_passenger),
        )
        self.enqueue(init_passenger)

        while True:
            minutes = random.gauss(5.0, 5.0)
            if minutes < 1.0:
                minutes = 1.0
            elif minutes > 9.0:
                minutes = 9.0

            interval_s = int(round(minutes * 60.0))
            yield env.timeout(interval_s)

            self.passenger_num += 1
            dest = choose_destination(self.station_id)
            passenger_id = self.passenger_num * 100 + self.station_id * 10 + dest
            passenger = {
                "passenger_id": passenger_id,
                "passenger_num": self.passenger_num,
                "origin": self.station_id,
                "destination": dest,
            }
            jsonl_emit(
                now=env.now,
                event="passenger_generated",
                entity_type="passenger_generator",
                station_id=self.station_id,
                payload=dict(passenger),
            )
            self.enqueue(passenger)


class Train:
    def __init__(self, env: simpy.Environment, stations: dict[int, Station]):
        self.env = env
        self.stations = stations
        self.onboard_by_dest = defaultdict(deque)

        self.route = [
            (1, 0),
            (2, 0),
            (3, 0),
            (4, 0),
            (5, 1),
            (4, 1),
            (3, 1),
            (2, 1),
        ]
        self.route_idx = 0

    def alight_process(self, station_id: int, *, until: float):
        q = self.onboard_by_dest.get(station_id)
        if not q:
            return

        while q:
            if self.env.now + 0.025 >= until:
                break
            yield self.env.timeout(0.025)
            passenger = q.popleft()
            jsonl_emit(
                now=self.env.now,
                event="passenger_exiting",
                entity_type="train_queue",
                station_id=station_id,
                payload=dict(passenger),
            )

        if station_id in self.onboard_by_dest and not self.onboard_by_dest[station_id]:
            del self.onboard_by_dest[station_id]

    def board_process(self, station_id: int, *, until: float):
        station = self.stations[station_id]
        while station.queue:
            if self.env.now + 0.025 >= until:
                break
            yield self.env.timeout(0.025)
            passenger = station.queue.popleft()
            jsonl_emit(
                now=self.env.now,
                event="passenger_boarding",
                entity_type="station_queue",
                station_id=station_id,
                payload=dict(passenger),
            )
            self.onboard_by_dest[passenger["destination"]].append(passenger)

    def run(self):
        while True:
            arrival_time = float(self.env.now)
            station_id, direction = self.route[self.route_idx]
            jsonl_emit(
                now=arrival_time,
                event="train_arrival",
                entity_type="train",
                station_id=station_id,
                payload={"station": station_id, "direction": direction},
            )

            next_arrival_target = arrival_time + 225.0
            alight = self.env.process(self.alight_process(station_id, until=next_arrival_target))
            board = self.env.process(self.board_process(station_id, until=next_arrival_target))
            yield alight & board

            self.route_idx = (self.route_idx + 1) % len(self.route)
            remaining = next_arrival_target - float(self.env.now)
            if remaining > 0:
                yield self.env.timeout(remaining)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="O-Train Light Rail DES Simulation")
    p.add_argument(
        "--simulate_time",
        type=parse_simulate_time,
        default=parse_simulate_time("00:01:00:000"),
        help='Simulation duration in "HH:MM:SS:mmm" (default 00:01:00:000)',
    )
    return p


def main(argv: list[str]) -> int:
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(levelname)s:%(message)s",
    )

    args = build_arg_parser().parse_args(argv)

    random.seed(time.time_ns())
    if xdevs is None:
        logging.info("xdevs not available; proceeding with simpy only")

    env = simpy.Environment()
    stations = {sid: Station(sid) for sid in STATION_NAMES.keys()}

    for station in stations.values():
        env.process(station.generate_passengers(env))

    train = Train(env, stations)
    env.process(train.run())

    simulate_end = float(args.simulate_time)
    deadline = time.monotonic() + 9.5

    try:
        while True:
            next_t = env.peek()
            if next_t == float("inf") or next_t > simulate_end:
                break
            if time.monotonic() > deadline:
                logging.warning("Wall-clock deadline reached; stopping simulation early")
                break
            env.step()
    except simpy.core.EmptySchedule:
        pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
