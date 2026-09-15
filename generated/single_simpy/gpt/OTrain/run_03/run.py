#!/usr/bin/env python3
import argparse
import sys
import json
import logging
import random
import time
from collections import deque, defaultdict

import simpy
import xdevs  # noqa: F401  (imported to match the allowed/available packages requirement)


STATION_NAMES = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro",
}

# Route sequence (station_id, direction) as specified
ROUTE_SEQUENCE = [
    (1, 0),
    (2, 0),
    (3, 0),
    (4, 0),
    (5, 1),
    (4, 1),
    (3, 1),
    (2, 1),
]
TRAVEL_INTERVAL_S = 225.0
SERIAL_DELAY_S = 0.025


def parse_hhmmssmmm(value: str) -> float:
    """
    Parse "HH:MM:SS:mmm" into seconds (float, millisecond precision).
    """
    try:
        parts = value.strip().split(":")
        if len(parts) != 4:
            raise ValueError("Expected 4 fields HH:MM:SS:mmm")
        hh, mm, ss, mmm = (int(p) for p in parts)
        if hh < 0 or mm < 0 or ss < 0 or mmm < 0:
            raise ValueError("Negative time component")
        if mm >= 60 or ss >= 60 or mmm >= 1000:
            raise ValueError("Out-of-range time component")
        return hh * 3600.0 + mm * 60.0 + ss * 1.0 + (mmm / 1000.0)
    except Exception as e:
        raise argparse.ArgumentTypeError(f"Invalid --simulate_time '{value}': {e}") from e


class EventLogger:
    def __init__(self, env: simpy.Environment, out_stream):
        self.env = env
        self.out = out_stream

    def emit(self, event: str, entity_type: str, station_id: int, payload: dict):
        if station_id not in STATION_NAMES:
            raise ValueError(f"Invalid station_id for event: {station_id}")
        obj = {
            "time": round(float(self.env.now), 3),
            "event": event,
            "entity_type": entity_type,
            "station_id": int(station_id),
            "station": STATION_NAMES[int(station_id)],
            "payload": payload,
        }
        print(json.dumps(obj, separators=(",", ":")), file=self.out)


class PassengerCounter:
    def __init__(self):
        self._n = 0  # next non-initial passenger_num will be 1

    def next_num(self) -> int:
        self._n += 1
        return self._n


class Station:
    def __init__(self, station_id: int):
        self.station_id = station_id
        self.queue = deque()  # FIFO of passenger payload dicts


class PassengerGenerator:
    """
    Generates passengers for a single station.
    - At t=0.5: creates special initialization passenger with passenger_id=0, passenger_num=0
    - Afterwards: normal arrivals with Normal(mean=5min, std=5min) clamped to [1,9] min
    """

    def __init__(self, env: simpy.Environment, logger: EventLogger, station: Station, counter: PassengerCounter):
        self.env = env
        self.logger = logger
        self.station = station
        self.counter = counter

    def _random_destination(self, origin: int) -> int:
        choices = [sid for sid in STATION_NAMES.keys() if sid != origin]
        return random.choice(choices)

    def _sample_interval_seconds(self) -> int:
        minutes = random.gauss(5.0, 5.0)
        minutes = max(1.0, min(9.0, minutes))  # clamp
        seconds = int(round(minutes * 60.0))
        # Guaranteed in [60,540] given clamp; keep defensively:
        return max(60, min(540, seconds))

    def run(self):
        # Initialization passenger at t=0.5
        yield self.env.timeout(0.5)
        origin = self.station.station_id
        dest = self._random_destination(origin)
        payload = {
            "passenger_id": 0,
            "passenger_num": 0,
            "origin": origin,
            "destination": dest,
        }
        # Validation: origin matches station, destination != origin
        if payload["origin"] == origin and payload["destination"] != origin:
            self.station.queue.append(payload)
            self.logger.emit(
                event="passenger_generated",
                entity_type="passenger_generator",
                station_id=origin,
                payload=payload,
            )

        # Normal passengers
        while True:
            interval_s = self._sample_interval_seconds()
            yield self.env.timeout(interval_s)

            origin = self.station.station_id
            dest = self._random_destination(origin)
            passenger_num = self.counter.next_num()
            passenger_id = passenger_num * 100 + origin * 10 + dest
            payload = {
                "passenger_id": int(passenger_id),
                "passenger_num": int(passenger_num),
                "origin": int(origin),
                "destination": int(dest),
            }

            # Validation: origin matches station, destination != origin, and encoding matches
            decoded_origin = (passenger_id // 10) % 10
            decoded_dest = passenger_id % 10
            if decoded_origin != origin or decoded_dest != dest or dest == origin:
                continue

            self.station.queue.append(payload)
            self.logger.emit(
                event="passenger_generated",
                entity_type="passenger_generator",
                station_id=origin,
                payload=payload,
            )


class Train:
    def __init__(self, env: simpy.Environment, logger: EventLogger, stations: dict[int, Station]):
        self.env = env
        self.logger = logger
        self.stations = stations
        # onboard grouped by destination: dest_station_id -> deque(payload)
        self.onboard = defaultdict(deque)

    def _alight_at_station(self, station_id: int):
        q = self.onboard.get(station_id)
        if not q:
            return
        while q:
            yield self.env.timeout(SERIAL_DELAY_S)
            payload = q.popleft()
            self.logger.emit(
                event="passenger_exiting",
                entity_type="train_queue",
                station_id=station_id,
                payload=payload,
            )
        # cleanup
        if station_id in self.onboard:
            del self.onboard[station_id]

    def _board_at_station(self, station_id: int):
        station = self.stations[station_id]
        while station.queue:
            yield self.env.timeout(SERIAL_DELAY_S)
            payload = station.queue.popleft()
            # Validation at boarding time
            if payload.get("origin") != station_id:
                continue
            if payload.get("destination") == station_id:
                continue
            self.onboard[payload["destination"]].append(payload)
            self.logger.emit(
                event="passenger_boarding",
                entity_type="station_queue",
                station_id=station_id,
                payload=payload,
            )

    def run(self):
        idx = 0
        while True:
            station_id, direction = ROUTE_SEQUENCE[idx]

            # Train arrival event
            self.logger.emit(
                event="train_arrival",
                entity_type="train",
                station_id=station_id,
                payload={"station": int(station_id), "direction": int(direction)},
            )

            # Alighting then boarding (both serial with 0.025s spacing from arrival)
            yield from self._alight_at_station(station_id)
            yield from self._board_at_station(station_id)

            # Travel to next stop
            idx = (idx + 1) % len(ROUTE_SEQUENCE)
            yield self.env.timeout(TRAVEL_INTERVAL_S)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="O-Train Light Rail Simulation (event-driven, stochastic)")
    p.add_argument(
        "--simulate_time",
        type=parse_hhmmssmmm,
        default=parse_hhmmssmmm("00:01:00:000"),
        help='Simulation duration in "HH:MM:SS:mmm" (default: 00:01:00:000)',
    )
    return p


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(levelname)s:%(message)s",
    )
    log = logging.getLogger("otrain")

    args = build_arg_parser().parse_args(argv)
    sim_duration = float(args.simulate_time)
    if sim_duration < 0.0:
        sim_duration = 0.0

    # Seed RNG from system time (as required)
    seed = time.time_ns()
    random.seed(seed)
    log.info("Seed=%s", seed)
    log.info("Simulating for %.3f seconds of simulation time", sim_duration)

    env = simpy.Environment()
    event_logger = EventLogger(env, sys.stdout)

    stations = {sid: Station(sid) for sid in STATION_NAMES.keys()}
    counter = PassengerCounter()

    # Start passenger generators (one per station)
    for sid in stations:
        gen = PassengerGenerator(env, event_logger, stations[sid], counter)
        env.process(gen.run())

    # Start train process
    train = Train(env, event_logger, stations)
    env.process(train.run())

    # Run simulation
    env.run(until=sim_duration)

    log.info("Simulation finished at t=%.3f", env.now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())