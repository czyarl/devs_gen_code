#!/usr/bin/env python3
import argparse
import json
import logging
import random
import sys
import time
from collections import deque
from typing import Deque, Dict, List, Optional

import numpy as np

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# -----------------------------
# Constants / Utilities
# -----------------------------

STATION_NAMES = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro",
}

INFINITY = float("inf")


def parse_hhmmssmmm(s: str) -> float:
    # "HH:MM:SS:mmm"
    parts = s.strip().split(":")
    if len(parts) != 4:
        raise ValueError("simulate_time must be in 'HH:MM:SS:mmm' format")
    hh, mm, ss, mmm = parts
    h = int(hh)
    m = int(mm)
    sec = int(ss)
    ms = int(mmm)
    if h < 0 or m < 0 or sec < 0 or ms < 0:
        raise ValueError("simulate_time components must be non-negative")
    return float(h * 3600 + m * 60 + sec) + float(ms) / 1000.0


def clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def round_ms(t: float) -> float:
    return float(f"{t:.3f}")


def make_event(time_s: float, event: str, entity_type: str, station_id: int, payload: dict) -> dict:
    return {
        "time": round_ms(time_s),
        "event": event,
        "entity_type": entity_type,
        "station_id": int(station_id),
        "station": STATION_NAMES[int(station_id)],
        "payload": payload,
    }


def sample_interval_seconds() -> int:
    # Normal(mean=5 min, std=5 min), clamp to [1, 9] minutes, convert to seconds and round to nearest integer.
    minutes = float(np.random.normal(loc=5.0, scale=5.0))
    minutes = clamp(minutes, 1.0, 9.0)
    seconds = int(round(minutes * 60.0))
    seconds = max(60, min(540, seconds))
    return seconds


def random_destination(origin: int) -> int:
    choices = [s for s in STATION_NAMES.keys() if s != origin]
    return int(random.choice(choices))


# -----------------------------
# Atomic Models
# -----------------------------

class PassengerGenerator(Atomic):
    """
    Generates passenger_generated events for a specific origin station.
    Outputs event dicts.
    """
    def __init__(self, name: str, parent: Coupled | None, origin_station_id: int):
        super().__init__(name)
        self.parent = parent
        self.origin = int(origin_station_id)

        self.add_out_port(Port(dict, "out_passenger"))

        self.t = 0.0
        self._phase = "PASSIVE"
        self._sigma = INFINITY
        self._next_time = INFINITY

        self.passenger_counter = 0  # passenger_num to use for next generated passenger (0 is init)
        self._pending_event: Optional[dict] = None

        self.hold_in("INIT", 0.0)

    def _schedule_emit(self, sigma: float, event_dict: dict):
        self._phase = "EMIT"
        self._sigma = float(sigma)
        self._next_time = self.t + self._sigma
        self._pending_event = event_dict
        self.hold_in("EMIT", self._sigma)

    def initialize(self):
        self.t = 0.0
        self.passenger_counter = 0

        # Initialization passenger at t=0.5 (ID=0), destination chosen uniformly from other 4 stations.
        dest = random_destination(self.origin)
        payload = {
            "passenger_id": 0,
            "passenger_num": 0,
            "origin": self.origin,
            "destination": dest,
        }
        ev = make_event(
            time_s=self.t + 0.5,
            event="passenger_generated",
            entity_type="passenger_generator",
            station_id=self.origin,
            payload=payload,
        )
        self._schedule_emit(0.5, ev)

    def lambdaf(self):
        if self._phase == "EMIT" and self._pending_event is not None:
            self.output["out_passenger"].add(self._pending_event)

    def deltint(self):
        # Advance time to internal event time
        self.t = self._next_time

        # Update passenger counter based on what just emitted
        if self.passenger_counter == 0:
            # just emitted init passenger_num=0
            self.passenger_counter = 1
        else:
            self.passenger_counter += 1

        # Schedule next passenger generation
        interval = sample_interval_seconds()
        dest = random_destination(self.origin)
        passenger_num = self.passenger_counter
        passenger_id = passenger_num * 100 + self.origin * 10 + dest
        payload = {
            "passenger_id": passenger_id,
            "passenger_num": passenger_num,
            "origin": self.origin,
            "destination": dest,
        }
        ev = make_event(
            time_s=self.t + interval,
            event="passenger_generated",
            entity_type="passenger_generator",
            station_id=self.origin,
            payload=payload,
        )
        self._schedule_emit(float(interval), ev)

    def deltext(self, e):
        # No inputs; just keep schedule
        self.t += float(e)
        remaining = self._next_time - self.t
        if remaining < 0.0:
            remaining = 0.0
        self._sigma = remaining
        self.hold_in(self._phase, self._sigma)

    def exit(self):
        pass


class StationQueue(Atomic):
    """
    Station passenger FIFO queue. On train arrival at its station, boards the snapshot batch serially:
    first at +0.025s, then every +0.025s.
    Outputs passenger_boarding events with the same payload schema as generation.
    """
    def __init__(self, name: str, parent: Coupled | None, station_id: int):
        super().__init__(name)
        self.parent = parent
        self.station_id = int(station_id)

        self.add_in_port(Port(dict, "in_passenger"))
        self.add_in_port(Port(dict, "in_train_arrival"))
        self.add_out_port(Port(dict, "out_boarding"))

        self.t = 0.0
        self._phase = "PASSIVE"
        self._sigma = INFINITY
        self._next_time = INFINITY

        self.queue: Deque[dict] = deque()
        self._batch_remaining = 0
        self._pending_board_event: Optional[dict] = None

        self.hold_in("INIT", 0.0)

    def _passivate(self):
        self._phase = "PASSIVE"
        self._sigma = INFINITY
        self._next_time = INFINITY
        self._pending_board_event = None
        self.hold_in("PASSIVE", INFINITY)

    def _schedule_next_board(self, delay: float):
        # delay relative to current self.t
        if self._batch_remaining <= 0 or not self.queue:
            self._passivate()
            return
        passenger = self.queue[0]  # do not pop until deltint
        ev = make_event(
            time_s=self.t + delay,
            event="passenger_boarding",
            entity_type="station_queue",
            station_id=self.station_id,
            payload=dict(passenger),
        )
        self._phase = "BOARD"
        self._sigma = float(delay)
        self._next_time = self.t + self._sigma
        self._pending_board_event = ev
        self.hold_in("BOARD", self._sigma)

    def initialize(self):
        self.t = 0.0
        self.queue.clear()
        self._batch_remaining = 0
        self._passivate()

    def lambdaf(self):
        if self._phase == "BOARD" and self._pending_board_event is not None:
            self.output["out_boarding"].add(self._pending_board_event)

    def deltint(self):
        # Advance time
        self.t = self._next_time

        if self._phase == "BOARD":
            if self._batch_remaining > 0 and self.queue:
                self.queue.popleft()
                self._batch_remaining -= 1

            if self._batch_remaining > 0 and self.queue:
                # Next boarding after 0.025s
                self._schedule_next_board(0.025)
            else:
                self._passivate()
        else:
            self._passivate()

    def deltext(self, e):
        self.t += float(e)

        # Gather new passengers
        for msg in list(self.input["in_passenger"].values):
            try:
                payload = msg.get("payload", {})
                origin = int(payload.get("origin"))
                dest = int(payload.get("destination"))
                if origin != self.station_id:
                    continue
                if dest == origin:
                    continue
                self.queue.append(
                    {
                        "passenger_id": int(payload["passenger_id"]),
                        "passenger_num": int(payload["passenger_num"]),
                        "origin": origin,
                        "destination": dest,
                    }
                )
            except Exception:
                # ignore malformed
                continue

        # Process train arrivals
        for msg in list(self.input["in_train_arrival"].values):
            try:
                st = int(msg.get("station_id", msg.get("payload", {}).get("station")))
            except Exception:
                continue
            if st != self.station_id:
                continue

            # Snapshot batch at arrival time: board only those already in queue at arrival
            self._batch_remaining = len(self.queue)
            if self._batch_remaining > 0:
                if self._phase != "BOARD":
                    self._schedule_next_board(0.025)

        # If already boarding, preserve schedule with remaining time
        if self._phase == "BOARD":
            remaining = self._next_time - self.t
            if remaining < 0.0:
                remaining = 0.0
            self._sigma = remaining
            self.hold_in("BOARD", self._sigma)
        else:
            self._passivate()

    def exit(self):
        pass


class TrainScheduler(Atomic):
    """
    Emits train_arrival at every stop.
    Arrival schedule is fixed: every 225 seconds.
    Route:
      1(S) -> 2(S) -> 3(S) -> 4(S) -> 5(N) -> 4(N) -> 3(N) -> 2(N) -> 1(S) -> ...
    direction: 0 southbound, 1 northbound.
    """
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_out_port(Port(dict, "out_arrival"))

        self.t = 0.0
        self._phase = "PASSIVE"
        self._sigma = INFINITY
        self._next_time = INFINITY

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
        self.idx = 0
        self._pending_arrival: Optional[dict] = None

        self.hold_in("INIT", 0.0)

    def _schedule_arrival(self, sigma: float, station_id: int, direction: int):
        ev = make_event(
            time_s=self.t + sigma,
            event="train_arrival",
            entity_type="train",
            station_id=station_id,
            payload={"station": station_id, "direction": int(direction)},
        )
        self._phase = "ARRIVAL"
        self._sigma = float(sigma)
        self._next_time = self.t + self._sigma
        self._pending_arrival = ev
        self.hold_in("ARRIVAL", self._sigma)

    def initialize(self):
        self.t = 0.0
        self.idx = 0
        st, d = self.route[self.idx]
        # Initial arrival at t=0 at Bayview, dir=0
        self._schedule_arrival(0.0, st, d)

    def lambdaf(self):
        if self._phase == "ARRIVAL" and self._pending_arrival is not None:
            self.output["out_arrival"].add(self._pending_arrival)

    def deltint(self):
        self.t = self._next_time
        # Move to next station in route, arriving exactly 225 seconds later
        self.idx = (self.idx + 1) % len(self.route)
        st, d = self.route[self.idx]
        self._schedule_arrival(225.0, st, d)

    def deltext(self, e):
        # No inputs; preserve schedule
        self.t += float(e)
        remaining = self._next_time - self.t
        if remaining < 0.0:
            remaining = 0.0
        self._sigma = remaining
        self.hold_in(self._phase, self._sigma)

    def exit(self):
        pass


class TrainQueue(Atomic):
    """
    Keeps onboard passengers grouped by destination. On train_arrival at station S,
    snapshots all passengers destined for S and makes them exit serially:
      first at +0.025, then every +0.025.
    Accepts passenger_boarding payloads from StationQueue.
    Outputs passenger_exiting events.
    """
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in_boarding"))
        self.add_in_port(Port(dict, "in_train_arrival"))
        self.add_out_port(Port(dict, "out_exiting"))

        self.t = 0.0
        self._phase = "PASSIVE"
        self._sigma = INFINITY
        self._next_time = INFINITY

        self.onboard_by_dest: Dict[int, Deque[dict]] = {i: deque() for i in STATION_NAMES.keys()}
        self._alight_station: Optional[int] = None
        self._alight_remaining = 0
        self._pending_exit_event: Optional[dict] = None

        self.hold_in("INIT", 0.0)

    def _passivate(self):
        self._phase = "PASSIVE"
        self._sigma = INFINITY
        self._next_time = INFINITY
        self._pending_exit_event = None
        self.hold_in("PASSIVE", INFINITY)

    def _schedule_next_exit(self, delay: float):
        if self._alight_station is None:
            self._passivate()
            return
        st = int(self._alight_station)
        q = self.onboard_by_dest.get(st)
        if q is None or self._alight_remaining <= 0 or not q:
            self._passivate()
            return
        passenger = q[0]  # do not pop until deltint
        ev = make_event(
            time_s=self.t + delay,
            event="passenger_exiting",
            entity_type="train_queue",
            station_id=st,
            payload=dict(passenger),
        )
        self._phase = "EXIT"
        self._sigma = float(delay)
        self._next_time = self.t + self._sigma
        self._pending_exit_event = ev
        self.hold_in("EXIT", self._sigma)

    def initialize(self):
        self.t = 0.0
        for k in self.onboard_by_dest:
            self.onboard_by_dest[k].clear()
        self._alight_station = None
        self._alight_remaining = 0
        self._passivate()

    def lambdaf(self):
        if self._phase == "EXIT" and self._pending_exit_event is not None:
            self.output["out_exiting"].add(self._pending_exit_event)

    def deltint(self):
        self.t = self._next_time

        if self._phase == "EXIT" and self._alight_station is not None:
            st = int(self._alight_station)
            q = self.onboard_by_dest.get(st)
            if q and self._alight_remaining > 0:
                q.popleft()
                self._alight_remaining -= 1

            if q and self._alight_remaining > 0:
                self._schedule_next_exit(0.025)
            else:
                self._alight_station = None
                self._alight_remaining = 0
                self._passivate()
        else:
            self._passivate()

    def deltext(self, e):
        self.t += float(e)

        # Process boarding
        for msg in list(self.input["in_boarding"].values):
            try:
                payload = msg.get("payload", {})
                origin = int(payload["origin"])
                dest = int(payload["destination"])
                if dest == origin:
                    continue
                if dest not in self.onboard_by_dest:
                    continue
                self.onboard_by_dest[dest].append(
                    {
                        "passenger_id": int(payload["passenger_id"]),
                        "passenger_num": int(payload["passenger_num"]),
                        "origin": origin,
                        "destination": dest,
                    }
                )
            except Exception:
                continue

        # Process train arrivals (trigger exiting)
        for msg in list(self.input["in_train_arrival"].values):
            try:
                st = int(msg.get("station_id", msg.get("payload", {}).get("station")))
            except Exception:
                continue
            if st not in self.onboard_by_dest:
                continue

            # Snapshot alighting batch
            if self._phase != "EXIT":
                self._alight_station = st
                self._alight_remaining = len(self.onboard_by_dest[st])
                if self._alight_remaining > 0:
                    self._schedule_next_exit(0.025)

        # Preserve schedule if already exiting
        if self._phase == "EXIT":
            remaining = self._next_time - self.t
            if remaining < 0.0:
                remaining = 0.0
            self._sigma = remaining
            self.hold_in("EXIT", self._sigma)
        elif self._phase != "EXIT":
            # If no schedule triggered
            if self._phase != "EXIT":
                if self._alight_remaining <= 0:
                    self._passivate()

    def exit(self):
        pass


class EventCollector(Atomic):
    """
    Collects event dicts and prints them as JSONL on stdout.
    All other logs must go to stderr.
    """
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "in_event"))

        self.t = 0.0
        self.hold_in("PASSIVE", INFINITY)

    def initialize(self):
        self.t = 0.0
        self.hold_in("PASSIVE", INFINITY)

    def lambdaf(self):
        # No outputs
        return

    def deltint(self):
        # Should never happen
        self.hold_in("PASSIVE", INFINITY)

    def deltext(self, e):
        self.t += float(e)
        for msg in list(self.input["in_event"].values):
            # Print exactly the event object as JSONL
            print(json.dumps(msg, separators=(",", ":")), file=sys.stdout, flush=True)
        self.hold_in("PASSIVE", INFINITY)

    def exit(self):
        pass


# -----------------------------
# Coupled System
# -----------------------------

class OTrainSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        collector = EventCollector("collector", parent=self)
        scheduler = TrainScheduler("train_scheduler", parent=self)
        train_queue = TrainQueue("train_queue", parent=self)

        self.add_component(collector)
        self.add_component(scheduler)
        self.add_component(train_queue)

        station_generators: Dict[int, PassengerGenerator] = {}
        station_queues: Dict[int, StationQueue] = {}

        for sid in sorted(STATION_NAMES.keys()):
            gen = PassengerGenerator(f"passenger_generator_{sid}", parent=self, origin_station_id=sid)
            q = StationQueue(f"station_queue_{sid}", parent=self, station_id=sid)
            station_generators[sid] = gen
            station_queues[sid] = q
            self.add_component(gen)
            self.add_component(q)

        # Couplings: arrivals to station queues + train queue + collector
        for sid in sorted(STATION_NAMES.keys()):
            self.add_coupling(scheduler.output["out_arrival"], station_queues[sid].input["in_train_arrival"])
        self.add_coupling(scheduler.output["out_arrival"], train_queue.input["in_train_arrival"])
        self.add_coupling(scheduler.output["out_arrival"], collector.input["in_event"])

        # Passenger generation to station queue + collector
        for sid in sorted(STATION_NAMES.keys()):
            self.add_coupling(station_generators[sid].output["out_passenger"], station_queues[sid].input["in_passenger"])
            self.add_coupling(station_generators[sid].output["out_passenger"], collector.input["in_event"])

        # Station boarding to train queue + collector
        for sid in sorted(STATION_NAMES.keys()):
            self.add_coupling(station_queues[sid].output["out_boarding"], train_queue.input["in_boarding"])
            self.add_coupling(station_queues[sid].output["out_boarding"], collector.input["in_event"])

        # Exiting to collector
        self.add_coupling(train_queue.output["out_exiting"], collector.input["in_event"])


# -----------------------------
# Main
# -----------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Ottawa O-Train Light Rail Simulation (xdevs.py)")
    parser.add_argument("--simulate_time", type=str, default="00:01:00:000",
                        help='Simulation duration in "HH:MM:SS:mmm" (default: 00:01:00:000)')
    args = parser.parse_args()

    try:
        sim_seconds = parse_hhmmssmmm(args.simulate_time)
    except Exception as ex:
        logging.error("Invalid --simulate_time: %s", ex)
        sys.exit(2)

    # Seed randomness from system time
    ns = time.time_ns()
    random.seed(ns)
    np.random.seed(ns % (2**32 - 1))

    # Hard cap to keep runtime bounded
    MAX_SIM_SECONDS = 7 * 24 * 3600.0
    if sim_seconds > MAX_SIM_SECONDS:
        logging.warning("simulate_time capped from %.3f to %.3f seconds to guarantee runtime.", sim_seconds, MAX_SIM_SECONDS)
        sim_seconds = MAX_SIM_SECONDS

    root = OTrainSystem(name="system", parent=None)
    coord = Coordinator(root, clock=SimulationClock(0.0))

    start_real = time.time()
    coord.initialize()

    # Run simulation (bounded)
    coord.simulate_time(sim_seconds)

    elapsed_real = time.time() - start_real
    if elapsed_real > 10.0:
        logging.warning("Simulation exceeded 10 seconds real time (%.3fs).", elapsed_real)


if __name__ == "__main__":
    main()