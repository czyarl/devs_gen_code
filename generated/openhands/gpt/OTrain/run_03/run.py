#!/usr/bin/env python3
"""O-Train light rail discrete-event simulation (SimPy).

STDOUT: JSONL simulation events only.
STDERR: logs/debug.

Run:
  python run.py --simulate_time 00:10:00:000
"""

import argparse
import json
import logging
import random
import sys
import time
from collections import defaultdict, deque

import simpy



def _seed_rng_from_system_time() -> int:
    """Seed RNG from system time (required by spec). Returns the seed used."""
    seed = time.time_ns()
    random.seed(seed)
    return seed


STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro",
}

ROUTE_STOPS = [
    (1, 0),
    (2, 0),
    (3, 0),
    (4, 0),
    (5, 1),
    (4, 1),
    (3, 1),
    (2, 1),
]

TRAVEL_SECONDS = 225.0
SERIAL_PROCESS_SECONDS = 0.025


def parse_hhmmssmmm(value: str) -> float:
    """Parse "HH:MM:SS:mmm" into seconds (float)."""
    parts = value.strip().split(":")
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("simulate_time must be HH:MM:SS:mmm")
    try:
        hh, mm, ss, mmm = (int(p) for p in parts)
    except ValueError as e:
        raise argparse.ArgumentTypeError("simulate_time must be numeric HH:MM:SS:mmm") from e

    if hh < 0 or not (0 <= mm < 60) or not (0 <= ss < 60) or not (0 <= mmm < 1000):
        raise argparse.ArgumentTypeError("simulate_time has out-of-range fields")

    return hh * 3600 + mm * 60 + ss + (mmm / 1000.0)


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


class Passenger:
    __slots__ = ("passenger_id", "passenger_num", "origin", "destination")

    def __init__(self, passenger_id: int, passenger_num: int, origin: int, destination: int) -> None:
        self.passenger_id = int(passenger_id)
        self.passenger_num = int(passenger_num)
        self.origin = int(origin)
        self.destination = int(destination)

    def payload(self) -> dict:
        return {
            "passenger_id": int(self.passenger_id),
            "passenger_num": int(self.passenger_num),
            "origin": int(self.origin),
            "destination": int(self.destination),
        }


class EventLogger:
    """JSONL event logger to stdout; debug to stderr via logging."""

    def __init__(self) -> None:
        self._out = sys.stdout

    @staticmethod
    def _event_base(now: float, event: str, entity_type: str, station_id: int) -> dict:
        return {
            "time": round(float(now), 3),
            "event": event,
            "entity_type": entity_type,
            "station_id": int(station_id),
            "station": STATIONS[int(station_id)],
        }

    def emit(self, now: float, event: str, entity_type: str, station_id: int, payload: dict) -> None:
        obj = self._event_base(now, event, entity_type, station_id)
        obj["payload"] = payload
        self._out.write(json.dumps(obj, separators=(",", ":")) + "\n")


class Station:
    def __init__(self, station_id: int) -> None:
        if station_id not in STATIONS:
            raise ValueError(f"invalid station_id {station_id}")
        self.station_id = station_id
        self.name = STATIONS[station_id]
        self.queue = deque()

    def enqueue(self, p: Passenger) -> None:
        # Validation: origin must match station; destination must differ.
        if p.origin != self.station_id:
            return
        if p.destination == p.origin:
            return

        # Additional validation for encoded passengers (except initialization id=0).
        if p.passenger_id != 0:
            decoded_origin = (p.passenger_id // 10) % 10
            decoded_dest = p.passenger_id % 10
            if decoded_origin != p.origin or decoded_dest != p.destination:
                return

        self.queue.append(p)


class PassengerIdSource:
    """Global passenger counter for unique IDs (except initialization passengers)."""

    def __init__(self) -> None:
        self._next_num = 1

    def next_passenger(self, origin: int, destination: int) -> Passenger:
        num = self._next_num
        self._next_num += 1
        pid = num * 100 + origin * 10 + destination
        return Passenger(passenger_id=pid, passenger_num=num, origin=origin, destination=destination)


class Train:
    def __init__(self, env: simpy.Environment, stations, logger: EventLogger) -> None:
        self.env = env
        self.stations = stations
        self.logger = logger
        # dest_station -> FIFO of onboard passengers for that destination
        self.onboard = defaultdict(deque)

    def board_passenger(self, p: Passenger) -> None:
        self.onboard[p.destination].append(p)

    def alight_for_station(self, station_id: int):
        dq = self.onboard.get(station_id)
        if not dq:
            return None
        p = dq.popleft()
        if not dq:
            self.onboard.pop(station_id, None)
        return p

    def process_alighting(self, station_id: int):
        """Serial alighting. First alight occurs +0.025s after arrival."""
        while True:
            p = self.alight_for_station(station_id)
            if p is None:
                break
            yield self.env.timeout(SERIAL_PROCESS_SECONDS)
            self.logger.emit(
                self.env.now,
                event="passenger_exiting",
                entity_type="train_queue",
                station_id=station_id,
                payload=p.payload(),
            )

    def process_boarding(self, station_id: int):
        """Serial boarding from station FIFO. First board occurs +0.025s after arrival."""
        st = self.stations[station_id]
        while st.queue:
            p = st.queue.popleft()
            yield self.env.timeout(SERIAL_PROCESS_SECONDS)
            self.board_passenger(p)
            self.logger.emit(
                self.env.now,
                event="passenger_boarding",
                entity_type="station_queue",
                station_id=station_id,
                payload=p.payload(),
            )

    def handle_stop(self, station_id: int):
        """Handle a stop: trigger alighting + boarding processes on arrival.

        The spec defines independent serial processes (0.025s per passenger) for
        alighting and boarding, both triggered by `train_arrival`.
        """
        alight_proc = self.env.process(self.process_alighting(station_id))
        board_proc = self.env.process(self.process_boarding(station_id))
        yield simpy.events.AllOf(self.env, [alight_proc, board_proc])

    def run(self):
        """Train scheduler.

        Generates a `train_arrival` at every stop. Per spec, the interval
        between consecutive station stops is 225 seconds. Boarding/alighting
        consume a small amount of that interval; the train then waits the
        remaining time so the next arrival is exactly +225s.
        """
        i = 0
        while True:
            station_id, direction = ROUTE_STOPS[i]
            arrival_t = float(self.env.now)

            self.logger.emit(
                self.env.now,
                event="train_arrival",
                entity_type="train",
                station_id=station_id,
                payload={"station": int(station_id), "direction": int(direction)},
            )

            # Stop activities are triggered by arrival.
            yield from self.handle_stop(station_id)

            # Keep the stop-to-stop interval exactly TRAVEL_SECONDS.
            elapsed = float(self.env.now) - arrival_t
            remaining = TRAVEL_SECONDS - elapsed
            if remaining > 0:
                yield self.env.timeout(remaining)

            i = (i + 1) % len(ROUTE_STOPS)


def passenger_generator_process(
    env: simpy.Environment,
    station: Station,
    pid_source: PassengerIdSource,
    logger: EventLogger,
):
    # Initialization passenger at t=0.5.
    yield env.timeout(0.5)
    init_dest = random.choice([sid for sid in STATIONS.keys() if sid != station.station_id])
    init_p = Passenger(passenger_id=0, passenger_num=0, origin=station.station_id, destination=init_dest)
    station.enqueue(init_p)
    logger.emit(
        env.now,
        event="passenger_generated",
        entity_type="passenger_generator",
        station_id=station.station_id,
        payload=init_p.payload(),
    )

    # Subsequent passengers.
    while True:
        # Interval in minutes: Normal(mean=5, std=5), clamped to [1,9].
        interval_min = random.gauss(5.0, 5.0)
        interval_min = clamp(interval_min, 1.0, 9.0)
        interval_seconds = int(round(interval_min * 60.0))
        yield env.timeout(interval_seconds)

        dest = random.choice([sid for sid in STATIONS.keys() if sid != station.station_id])
        p = pid_source.next_passenger(origin=station.station_id, destination=dest)
        station.enqueue(p)
        logger.emit(
            env.now,
            event="passenger_generated",
            entity_type="passenger_generator",
            station_id=station.station_id,
            payload=p.payload(),
        )


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="O-Train light rail simulation (DES via SimPy)")
    p.add_argument(
        "--simulate_time",
        type=str,
        default="00:01:00:000",
        help='Simulation duration in "HH:MM:SS:mmm" (default: 00:01:00:000)',
    )
    return p


def main(argv=None) -> int:
    # Seed random using system time (required).
    seed = _seed_rng_from_system_time()

    logging.basicConfig(
        stream=sys.stderr,
        level=logging.INFO,
        format="%(levelname)s %(message)s",
    )
    log = logging.getLogger("otrain")

    args = build_arg_parser().parse_args(argv)
    try:
        simulate_seconds = parse_hhmmssmmm(args.simulate_time)
    except argparse.ArgumentTypeError as e:
        log.error(str(e))
        return 2

    log.info("seed=%s simulate_seconds=%.3f", seed, simulate_seconds)

    env = simpy.Environment()
    logger = EventLogger()

    stations = {sid: Station(sid) for sid in STATIONS.keys()}
    pid_source = PassengerIdSource()

    # Start passenger generators.
    for st in stations.values():
        env.process(passenger_generator_process(env, st, pid_source, logger))

    # Start train.
    train = Train(env, stations, logger)
    env.process(train.run())

    # Run simulation with a wall-clock safety watchdog (spec requires <=10s real time).
    start_wall = time.monotonic()
    max_wall = 9.5

    if simulate_seconds < env.now:
        simulate_seconds = env.now

    # Run the environment step-by-step to enforce a wall-clock cap.
    # Note: SimPy Timeout events have .triggered=True immediately on creation;
    # use .processed to detect completion.
    stop_event = env.timeout(max(0.0, simulate_seconds - env.now))

    while not stop_event.processed:
        if (time.monotonic() - start_wall) > max_wall:
            log.warning(
                "wallclock_limit_reached elapsed=%.3f now=%.3f target=%.3f",
                time.monotonic() - start_wall,
                env.now,
                simulate_seconds,
            )
            break
        env.step()

    # If we reached the stop event, also process any other events scheduled at
    # exactly the same simulation time.
    while stop_event.processed and env.peek() <= simulate_seconds:
        if (time.monotonic() - start_wall) > max_wall:
            log.warning(
                "wallclock_limit_reached elapsed=%.3f now=%.3f target=%.3f",
                time.monotonic() - start_wall,
                env.now,
                simulate_seconds,
            )
            break
        env.step()

    log.info("simulation_complete now=%.3f", env.now)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
