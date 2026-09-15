#!/usr/bin/env python3
import argparse
import sys
import json
import logging
import random
import time
import math
from collections import deque, defaultdict

import simpy  # noqa: F401 (allowed; not used)
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


STATION_NAMES = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro",
}


def parse_hhmmssmmm(s: str) -> float:
    # "HH:MM:SS:mmm"
    parts = s.strip().split(":")
    if len(parts) != 4:
        raise ValueError("simulate_time must be in 'HH:MM:SS:mmm' format")
    hh, mm, ss, mmm = (int(p) for p in parts)
    if hh < 0 or mm < 0 or ss < 0 or mmm < 0:
        raise ValueError("simulate_time components must be non-negative")
    return hh * 3600.0 + mm * 60.0 + ss * 1.0 + (mmm / 1000.0)


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def emit_event(t: float, event: str, entity_type: str, station_id: int, payload: dict) -> None:
    obj = {
        "time": round(float(t), 3),
        "event": event,
        "entity_type": entity_type,
        "station_id": int(station_id),
        "station": STATION_NAMES[int(station_id)],
        "payload": payload,
    }
    print(json.dumps(obj, separators=(",", ":")), file=sys.stdout, flush=True)


def _finite_remaining_sigma(current_sigma: float, e: float) -> float:
    if math.isinf(current_sigma):
        return float("inf")
    return max(0.0, float(current_sigma) - float(e))


class TimeAwareAtomic(Atomic):
    """
    Track local t_last using DEVS elapsed time 'e' and sigma.
    At lambdaf time, event time is (t_last + sigma).
    """

    def __init__(self, name: str):
        super().__init__(name)
        self.t_last = 0.0

    def _lambda_time(self) -> float:
        return float(self.t_last) + float(self.sigma)

    def _advance_internal_time(self) -> None:
        # Called at start of deltint to advance time to t_next
        old_sigma = float(self.sigma)
        if not math.isinf(old_sigma):
            self.t_last += old_sigma

    def _advance_external_time(self, e: float) -> None:
        self.t_last += float(e)


class PassengerGenerator(TimeAwareAtomic):
    def __init__(self, name: str, parent: Coupled | None, station_id: int):
        super().__init__(name)
        self.parent = parent
        self.station_id = int(station_id)

        self.add_out_port(Port(dict, "passenger_out"))

        self.passenger_num = 0
        self._pending_payload = None

    def _sample_interval_seconds(self) -> int:
        mins = random.gauss(5.0, 5.0)
        mins = clamp(mins, 1.0, 9.0)
        sec = int(round(mins * 60.0))
        return max(1, sec)

    def _new_passenger_payload(self, passenger_num: int, initial: bool = False) -> dict:
        origin = self.station_id
        destination = random.choice([sid for sid in range(1, 6) if sid != origin])
        if initial:
            passenger_id = 0
            passenger_num_field = 0
        else:
            passenger_id = passenger_num * 100 + origin * 10 + destination
            passenger_num_field = passenger_num
        return {
            "passenger_id": int(passenger_id),
            "passenger_num": int(passenger_num_field),
            "origin": int(origin),
            "destination": int(destination),
        }

    def initialize(self):
        self.t_last = 0.0
        self.passenger_num = 0
        # Initial passenger at t=0.5
        self._pending_payload = self._new_passenger_payload(passenger_num=0, initial=True)
        self.hold_in("GENERATE", 0.5)

    def lambdaf(self):
        payload = self._pending_payload
        if payload is None:
            return
        t = self._lambda_time()
        emit_event(
            t=t,
            event="passenger_generated",
            entity_type="passenger_generator",
            station_id=self.station_id,
            payload=payload,
        )
        self.output["passenger_out"].add(payload)

    def deltint(self):
        self._advance_internal_time()

        # After outputting initial passenger, start numbering from 1
        if self.passenger_num == 0 and self._pending_payload and self._pending_payload.get("passenger_id") == 0:
            self.passenger_num = 1
        else:
            self.passenger_num += 1

        self._pending_payload = self._new_passenger_payload(passenger_num=self.passenger_num, initial=False)
        dt = self._sample_interval_seconds()
        self.hold_in("GENERATE", float(dt))

    def deltext(self, e):
        self._advance_external_time(e)
        # No inputs; keep schedule
        self.hold_in(self.phase, _finite_remaining_sigma(self.sigma, e))

    def exit(self):
        pass


class Train(TimeAwareAtomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_out_port(Port(dict, "arrival_out"))

        # Cyclic stop sequence (station_id, direction)
        # 0=Southbound, 1=Northbound
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
        self.idx = 0
        self._pending_arrival = None

    def initialize(self):
        self.t_last = 0.0
        self.idx = 0
        station_id, direction = self.route[self.idx]
        self._pending_arrival = {"station": int(station_id), "direction": int(direction)}
        # Initial arrival at t=0.0 Bayview, dir=0
        self.hold_in("ARRIVE", 0.0)

    def lambdaf(self):
        if self._pending_arrival is None:
            return
        t = self._lambda_time()
        station_id = int(self._pending_arrival["station"])
        emit_event(
            t=t,
            event="train_arrival",
            entity_type="train",
            station_id=station_id,
            payload={"station": station_id, "direction": int(self._pending_arrival["direction"])},
        )
        self.output["arrival_out"].add(dict(self._pending_arrival))

    def deltint(self):
        self._advance_internal_time()

        self.idx = (self.idx + 1) % len(self.route)
        station_id, direction = self.route[self.idx]
        self._pending_arrival = {"station": int(station_id), "direction": int(direction)}
        self.hold_in("ARRIVE", 225.0)

    def deltext(self, e):
        self._advance_external_time(e)
        # No inputs; keep schedule
        self.hold_in(self.phase, _finite_remaining_sigma(self.sigma, e))

    def exit(self):
        pass


class StationQueue(TimeAwareAtomic):
    def __init__(self, name: str, parent: Coupled | None, station_id: int):
        super().__init__(name)
        self.parent = parent
        self.station_id = int(station_id)

        self.add_in_port(Port(dict, "passenger_in"))
        self.add_in_port(Port(dict, "train_arrival_in"))
        self.add_out_port(Port(dict, "boarding_out"))

        self.q = deque()
        self.train_present = False

        self._pending_board = None  # passenger payload

    def initialize(self):
        self.t_last = 0.0
        self.q.clear()
        self.train_present = False
        self._pending_board = None
        self.hold_in("PASSIVE", float("inf"))

    def _validate_and_enqueue(self, p: dict):
        try:
            origin = int(p["origin"])
            destination = int(p["destination"])
        except Exception:
            return
        if origin != self.station_id:
            return
        if destination == origin:
            return
        self.q.append(p)

    def _maybe_start_or_continue_boarding(self, first_delay: float = 0.025):
        if self.train_present and self.q:
            # If not already scheduled to board, schedule
            if self.phase != "BOARD":
                self._pending_board = self.q[0]
                self.hold_in("BOARD", float(first_delay))
        else:
            if not self.q:
                self.train_present = False
            self._pending_board = None
            self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        if self.phase != "BOARD" or self._pending_board is None:
            return
        t = self._lambda_time()
        payload = self._pending_board

        emit_event(
            t=t,
            event="passenger_boarding",
            entity_type="station_queue",
            station_id=self.station_id,
            payload=dict(payload),
        )
        self.output["boarding_out"].add(dict(payload))

    def deltint(self):
        self._advance_internal_time()

        if self.phase == "BOARD":
            # Commit the boarding (remove from FIFO)
            if self.q and self._pending_board is not None and self.q[0] == self._pending_board:
                self.q.popleft()
            elif self.q:
                # Defensive: remove first anyway
                self.q.popleft()

            if self.train_present and self.q:
                self._pending_board = self.q[0]
                self.hold_in("BOARD", 0.025)
            else:
                if not self.q:
                    self.train_present = False
                self._pending_board = None
                self.hold_in("PASSIVE", float("inf"))
            return

        # PASSIVE internal shouldn't happen
        self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        self._advance_external_time(e)

        # Read inputs
        for p in list(self.input["passenger_in"].values):
            self._validate_and_enqueue(p)

        arrival_for_me = False
        for a in list(self.input["train_arrival_in"].values):
            try:
                if int(a.get("station")) == self.station_id:
                    arrival_for_me = True
                    self.train_present = True
            except Exception:
                continue

        if self.phase == "BOARD":
            # Keep current schedule; queue may have grown
            rem = _finite_remaining_sigma(self.sigma, e)
            self.hold_in("BOARD", rem)
            return

        # PASSIVE -> possibly start boarding
        if arrival_for_me:
            self._maybe_start_or_continue_boarding(first_delay=0.025)
        else:
            # If train is still present (dwell) and passengers arrive, allow boarding
            if self.train_present and self.q:
                self._maybe_start_or_continue_boarding(first_delay=0.025)
            else:
                self.hold_in("PASSIVE", float("inf"))

    def exit(self):
        pass


class TrainQueue(TimeAwareAtomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.add_in_port(Port(dict, "boarding_in"))
        self.add_in_port(Port(dict, "train_arrival_in"))

        self.passengers_by_dest = defaultdict(deque)  # dest -> deque(passenger_payload)
        self.current_station = None

        self.exiting = deque()
        self._pending_exit = None

    def initialize(self):
        self.t_last = 0.0
        self.passengers_by_dest.clear()
        self.current_station = None
        self.exiting.clear()
        self._pending_exit = None
        self.hold_in("PASSIVE", float("inf"))

    def lambdaf(self):
        if self.phase != "EXIT" or self._pending_exit is None:
            return
        t = self._lambda_time()
        payload = self._pending_exit
        station_id = int(self.current_station) if self.current_station is not None else int(payload["destination"])

        emit_event(
            t=t,
            event="passenger_exiting",
            entity_type="train_queue",
            station_id=station_id,
            payload=dict(payload),
        )

    def deltint(self):
        self._advance_internal_time()

        if self.phase == "EXIT":
            # Commit the exit
            if self.exiting:
                self.exiting.popleft()
            if self.exiting:
                self._pending_exit = self.exiting[0]
                self.hold_in("EXIT", 0.025)
            else:
                self._pending_exit = None
                self.hold_in("PASSIVE", float("inf"))
            return

        self.hold_in("PASSIVE", float("inf"))

    def deltext(self, e):
        self._advance_external_time(e)

        # Boardings: add passengers
        for p in list(self.input["boarding_in"].values):
            try:
                dest = int(p["destination"])
                origin = int(p["origin"])
            except Exception:
                continue
            if dest < 1 or dest > 5 or origin < 1 or origin > 5 or dest == origin:
                continue
            self.passengers_by_dest[dest].append(p)

        # Train arrivals: start exiting process for that station
        new_station = None
        for a in list(self.input["train_arrival_in"].values):
            try:
                new_station = int(a.get("station"))
            except Exception:
                continue

        if self.phase == "EXIT":
            # Continue current schedule; also update current_station to latest arrival if present,
            # but do not interrupt an ongoing exiting sequence.
            if new_station is not None:
                self.current_station = new_station
            rem = _finite_remaining_sigma(self.sigma, e)
            self.hold_in("EXIT", rem)
            return

        if new_station is not None:
            self.current_station = new_station
            dq = self.passengers_by_dest.get(new_station)
            if dq and len(dq) > 0:
                self.exiting = dq
                self.passengers_by_dest[new_station] = deque()
                self._pending_exit = self.exiting[0]
                self.hold_in("EXIT", 0.025)
                return

        self.hold_in("PASSIVE", float("inf"))

    def exit(self):
        pass


class OTrainSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        train = Train("train", parent=self)
        train_queue = TrainQueue("train_queue", parent=self)

        self.add_component(train)
        self.add_component(train_queue)

        station_queues = {}
        generators = {}

        for sid in range(1, 6):
            gen = PassengerGenerator(f"passenger_generator_{sid}", parent=self, station_id=sid)
            sq = StationQueue(f"station_queue_{sid}", parent=self, station_id=sid)
            generators[sid] = gen
            station_queues[sid] = sq
            self.add_component(gen)
            self.add_component(sq)

        # Couplings
        for sid in range(1, 6):
            self.add_coupling(generators[sid].output["passenger_out"], station_queues[sid].input["passenger_in"])
            self.add_coupling(train.output["arrival_out"], station_queues[sid].input["train_arrival_in"])
            self.add_coupling(station_queues[sid].output["boarding_out"], train_queue.input["boarding_in"])

        self.add_coupling(train.output["arrival_out"], train_queue.input["train_arrival_in"])


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(levelname)s:%(message)s")
    logging.getLogger("xdevs").setLevel(logging.ERROR)

    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=str, default="00:01:00:000",
                        help="Simulation duration in 'HH:MM:SS:mmm' (default: 00:01:00:000)")
    args = parser.parse_args()

    try:
        sim_time = parse_hhmmssmmm(args.simulate_time)
    except Exception as ex:
        print(f"ERROR: {ex}", file=sys.stderr, flush=True)
        sys.exit(2)

    # Safety clamp to ensure completion well under 10 seconds wall time.
    # (Event rate is low, but this guarantees bounded runtime for extreme inputs.)
    max_sim_time = 6 * 3600.0  # 6 hours
    if sim_time > max_sim_time:
        print(f"WARNING: simulate_time too large ({sim_time}s). Clamping to {max_sim_time}s.",
              file=sys.stderr, flush=True)
        sim_time = max_sim_time

    seed = time.time_ns()
    random.seed(seed)
    print(f"seed={seed}", file=sys.stderr, flush=True)

    root = OTrainSystem(name="system", parent=None)
    coord = Coordinator(root, clock=SimulationClock(0.0))
    coord.initialize()
    coord.simulate_time(float(sim_time))


if __name__ == "__main__":
    main()