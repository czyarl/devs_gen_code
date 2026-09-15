import argparse
import sys
import json
import logging
import random
import time
from collections import deque, defaultdict

import simpy


STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro",
}


def parse_simulate_time(s: str) -> float:
    """Parse HH:MM:SS:mmm into seconds as float."""
    try:
        hh, mm, ss, mmm = s.strip().split(":")
        hh_i = int(hh)
        mm_i = int(mm)
        ss_i = int(ss)
        mmm_i = int(mmm)
        if any(x < 0 for x in (hh_i, mm_i, ss_i, mmm_i)):
            raise ValueError
        if mm_i >= 60 or ss_i >= 60 or mmm_i >= 1000:
            raise ValueError
        return hh_i * 3600.0 + mm_i * 60.0 + ss_i + (mmm_i / 1000.0)
    except Exception as e:
        raise argparse.ArgumentTypeError(
            f"Invalid --simulate_time '{s}'. Expected HH:MM:SS:mmm"
        ) from e


class RealTimeLimitReached(Exception):
    pass


class EventSink:
    """Writes JSONL events to stdout and logs diagnostics to stderr."""

    def __init__(self, real_time_budget_s: float = 9.5, max_events: int = 250_000):
        self._t0 = time.monotonic()
        self._budget = float(real_time_budget_s)
        self._max_events = int(max_events)
        self._events = 0

    def _check_budget(self):
        if self._events >= self._max_events:
            raise RealTimeLimitReached(f"max_events exceeded: {self._max_events}")
        if (time.monotonic() - self._t0) > self._budget:
            raise RealTimeLimitReached("real-time budget exceeded")

    def emit(self, sim_time: float, event: str, entity_type: str, station_id: int, payload: dict):
        self._check_budget()
        if station_id not in STATIONS:
            raise ValueError(f"station_id out of range: {station_id}")
        obj = {
            "time": round(float(sim_time), 3),
            "event": event,
            "entity_type": entity_type,
            "station_id": int(station_id),
            "station": STATIONS[int(station_id)],
            "payload": payload,
        }
        sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
        self._events += 1


class Station:
    def __init__(self, env: simpy.Environment, station_id: int, sink: EventSink):
        self.env = env
        self.station_id = station_id
        self.sink = sink
        self.queue = deque()  # FIFO of passenger dicts
        self._passenger_num = 0

    def _choose_destination(self) -> int:
        choices = [sid for sid in STATIONS.keys() if sid != self.station_id]
        return random.choice(choices)

    def _make_passenger(self, passenger_num: int, destination: int, passenger_id: int | None = None) -> dict:
        origin = self.station_id
        if destination == origin:
            raise ValueError("destination must differ from origin")
        if passenger_id is None:
            passenger_id = passenger_num * 100 + origin * 10 + destination
        return {
            "passenger_id": int(passenger_id),
            "passenger_num": int(passenger_num),
            "origin": int(origin),
            "destination": int(destination),
        }

    def generate_process(self):
        # Special initialization passenger at t=0.5
        yield self.env.timeout(0.5)
        init_dest = self._choose_destination()
        p = self._make_passenger(passenger_num=0, destination=init_dest, passenger_id=0)
        self.queue.append(p)
        self.sink.emit(self.env.now, "passenger_generated", "passenger_generator", self.station_id, p)

        # Ongoing passengers
        while True:
            minutes = random.gauss(5.0, 5.0)
            minutes = max(1.0, min(9.0, minutes))
            interval_s = int(round(minutes * 60.0))
            yield self.env.timeout(interval_s)

            self._passenger_num += 1
            dest = self._choose_destination()
            p = self._make_passenger(passenger_num=self._passenger_num, destination=dest)
            # Validation: encoded origin must match station, destination different
            if p["origin"] == self.station_id and p["destination"] != self.station_id:
                self.queue.append(p)
                self.sink.emit(self.env.now, "passenger_generated", "passenger_generator", self.station_id, p)


class Train:
    def __init__(self, env: simpy.Environment, sink: EventSink, stations: dict[int, Station]):
        self.env = env
        self.sink = sink
        self.stations = stations
        self.by_destination: dict[int, deque] = defaultdict(deque)

        # Route sequence (station_id, direction)
        # Note: do NOT duplicate the first stop at the end; the cycle wraps.
        self.route = [
            (1, 0),  # Bayview, southbound
            (2, 0),
            (3, 0),
            (4, 0),
            (5, 1),  # Greenboro, switch to northbound
            (4, 1),
            (3, 1),
            (2, 1),
            # next wraps back to (1,0)
        ]

    def _start_alighting(self, station_id: int, arrival_time: float):
        def proc():
            yield self.env.timeout(0.025)
            q = self.by_destination.get(station_id)
            while q and len(q) > 0:
                p = q.popleft()
                self.sink.emit(self.env.now, "passenger_exiting", "train_queue", station_id, dict(p))
                yield self.env.timeout(0.025)

        self.env.process(proc())

    def _start_boarding(self, station_id: int, arrival_time: float):
        station = self.stations[station_id]

        def proc():
            yield self.env.timeout(0.025)
            while len(station.queue) > 0:
                p = station.queue.popleft()
                self.by_destination[p["destination"]].append(p)
                self.sink.emit(self.env.now, "passenger_boarding", "station_queue", station_id, dict(p))
                yield self.env.timeout(0.025)

        self.env.process(proc())

    def run(self):
        # Initial arrival at t=0 at Bayview dir=0
        idx = 0
        while True:
            station_id, direction = self.route[idx]
            self.sink.emit(
                self.env.now,
                "train_arrival",
                "train",
                station_id,
                {"station": int(station_id), "direction": int(direction)},
            )

            # Trigger alighting and boarding (both start 0.025s after arrival)
            self._start_alighting(station_id, self.env.now)
            self._start_boarding(station_id, self.env.now)

            # Move to next station
            yield self.env.timeout(225.0)
            idx = (idx + 1) % len(self.route)


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="O-Train light rail DES simulation (SimPy)")
    p.add_argument(
        "--simulate_time",
        type=str,
        default="00:01:00:000",
        help='Simulation duration as "HH:MM:SS:mmm" (default: 00:01:00:000)',
    )
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = build_arg_parser()
    args = parser.parse_args(argv)
    sim_duration = parse_simulate_time(args.simulate_time)

    # Seed RNG from system time
    seed = time.time_ns()
    random.seed(seed)
    logging.info("seed=%s simulate_time_s=%.3f", seed, sim_duration)

    env = simpy.Environment()
    sink = EventSink(real_time_budget_s=9.5, max_events=250_000)

    stations = {sid: Station(env, sid, sink) for sid in STATIONS}
    for st in stations.values():
        env.process(st.generate_process())

    train = Train(env, sink, stations)
    env.process(train.run())

    try:
        env.run(until=sim_duration)
    except RealTimeLimitReached as e:
        logging.warning("Stopping early: %s", e)
    except Exception:
        logging.exception("Simulation error")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
