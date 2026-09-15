import argparse
import sys
import json
import logging
import time
import random
import math
from collections import deque

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Set seed for reproducibility
random.seed(time.time_ns())
numpy_seed = time.time_ns() % (2**32 - 1)
try:
    import numpy as np
    np.random.seed(numpy_seed)
except ImportError:
    pass  # Fallback to standard random if numpy not available

# Station configuration
STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro"
}

# Direction constants
SOUTHBOUND = 0
NORTHBOUND = 1

class PassengerGenerator(Atomic):
    def __init__(self, station_id, name=None, parent=None):
        super().__init__(name or f"passenger_generator_{station_id}")
        self.station_id = station_id
        self.station_name = STATIONS[station_id]
        self.passenger_num = 0
        self.passenger_queue = deque()
        self.next_generation_time = 0.0
        self.hold_in("INIT", 0)

    def initialize(self):
        # Generate initial passenger at t=0.5
        self.passenger_num = 0
        payload = {
            "passenger_id": 0,
            "passenger_num": 0,
            "origin": self.station_id,
            "destination": None
        }
        event = {
            "time": 0.5,
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": self.station_id,
            "station": self.station_name,
            "payload": payload
        }
        print(json.dumps(event), file=sys.stdout, flush=True)
        self.passenger_num += 1
        self.schedule_next_generation()

    def schedule_next_generation(self):
        # Generate interval using normal distribution
        interval = random.normalvariate(5.0 * 60, 5.0 * 60)  # Mean 5 min, std 5 min
        interval = max(1 * 60, min(9 * 60, interval))  # Clamp to [1, 9] minutes
        interval = round(interval)  # Round to nearest second
        self.next_generation_time += interval
        self.hold_in("WAITING", interval)

    def lambdaf(self):
        pass

    def deltint(self):
        self.passenger_num += 1
        # Generate a new passenger
        destinations = [i for i in range(1, 6) if i != self.station_id]
        destination = random.choice(destinations)
        passenger_id = self.passenger_num * 100 + self.station_id * 10 + destination
        payload = {
            "passenger_id": passenger_id,
            "passenger_num": self.passenger_num,
            "origin": self.station_id,
            "destination": destination
        }
        event = {
            "time": self.next_generation_time,
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": self.station_id,
            "station": self.station_name,
            "payload": payload
        }
        print(json.dumps(event), file=sys.stdout, flush=True)
        self.schedule_next_generation()

    def deltext(self, e):
        pass

    def exit(self):
        pass

class StationQueue(Atomic):
    def __init__(self, station_id, name=None, parent=None):
        super().__init__(name or f"station_queue_{station_id}")
        self.station_id = station_id
        self.station_name = STATIONS[station_id]
        self.passenger_queue = deque()
        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        if e == "passenger_generated":
            # Add passenger to queue
            passenger = self.input["passenger_generated"].values[0]
            self.passenger_queue.append(passenger)
            self.hold_in("IDLE", 0)
        elif e == "train_arrival":
            # Process boarding
            passengers_to_board = []
            while self.passenger_queue and len(passengers_to_board) < 50:
                p = self.passenger_queue.popleft()
                if p["payload"]["origin"] == self.station_id:
                    passengers_to_board.append(p)
                else:
                    # Requeue if not for this station
                    self.passenger_queue.appendleft(p)
                    break
            # Send boarding events
            boarding_time = self.time_last + 0.025
            for i, p in enumerate(passengers_to_board):
                payload = p["payload"]
                payload["board_time"] = boarding_time + i * 0.025
                event = {
                    "time": payload["board_time"],
                    "event": "passenger_boarding",
                    "entity_type": "station_queue",
                    "station_id": self.station_id,
                    "station": self.station_name,
                    "payload": payload
                }
                print(json.dumps(event), file=sys.stdout, flush=True)
            self.hold_in("IDLE", 0)

    def exit(self):
        pass

class TrainQueue(Atomic):
    def __init__(self, name=None, parent=None):
        super().__init__(name or "train_queue")
        self.passengers = []
        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        if e == "passenger_boarding":
            passenger = self.input["passenger_boarding"].values[0]
            self.passengers.append(passenger)
            self.hold_in("IDLE", 0)
        elif e == "train_arrival":
            # Process alighting
            passengers_to_alight = []
            alighting_time = self.time_last + 0.025
            for i, p in enumerate(self.passengers):
                if p["payload"]["destination"] == self.input["train_arrival"].values[0]["payload"]["station"]:
                    passengers_to_alight.append(p)
            # Remove alighted passengers
            for p in passengers_to_alight:
                self.passengers.remove(p)
            # Send exiting events
            for i, p in enumerate(passengers_to_alight):
                payload = p["payload"]
                payload["alight_time"] = alighting_time + i * 0.025
                event = {
                    "time": payload["alight_time"],
                    "event": "passenger_exiting",
                    "entity_type": "train_queue",
                    "station_id": payload["destination"],
                    "station": STATIONS[payload["destination"]],
                    "payload": payload
                }
                print(json.dumps(event), file=sys.stdout, flush=True)
            self.hold_in("IDLE", 0)

    def exit(self):
        pass

class TrainScheduler(Atomic):
    def __init__(self, name=None, parent=None):
        super().__init__(name or "train_scheduler")
        self.route = [
            (1, SOUTHBOUND), (2, SOUTHBOUND), (3, SOUTHBOUND), (4, SOUTHBOUND),
            (5, NORTHBOUND), (4, NORTHBOUND), (3, NORTHBOUND), (2, NORTHBOUND),
            (1, SOUTHBOUND)
        ]
        self.current_station = 0
        self.direction = SOUTHBOUND
        self.current_time = 0.0
        self.hold_in("INIT", 0)

    def initialize(self):
        self.current_time = 0.0
        self.current_station = 0
        self.direction = SOUTHBOUND
        self.schedule_next_arrival()

    def schedule_next_arrival(self):
        station_id, direction = self.route[self.current_station]
        self.current_time += 225.0  # 225 seconds between stations
        payload = {
            "station": station_id,
            "direction": direction
        }
        event = {
            "time": self.current_time,
            "event": "train_arrival",
            "entity_type": "train",
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": payload
        }
        print(json.dumps(event), file=sys.stdout, flush=True)
        self.current_station = (self.current_station + 1) % len(self.route)
        self.hold_in("WAITING", 225.0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.schedule_next_arrival()

    def deltext(self, e):
        pass

    def exit(self):
        pass

class OTrainSystem(Coupled):
    def __init__(self, name="otrain_system", parent=None, simulate_time=60.0):
        super().__init__(name, parent)
        self.simulate_time = simulate_time

        # Create components
        self.train_scheduler = TrainScheduler(name="train_scheduler")
        self.passenger_generators = [PassengerGenerator(i, name=f"passenger_generator_{i}") for i in range(1, 6)]
        self.station_queues = [StationQueue(i, name=f"station_queue_{i}") for i in range(1, 6)]
        self.train_queue = TrainQueue(name="train_queue")

        # Add components
        self.add_component(self.train_scheduler)
        for pg in self.passenger_generators:
            self.add_component(pg)
        for sq in self.station_queues:
            self.add_component(sq)
        self.add_component(self.train_queue)

        # Define couplings
        # Train scheduler to all station queues
        for i in range(1, 6):
            self.add_coupling(self.train_scheduler.output["train_arrival"], self.station_queues[i-1].input["train_arrival"])
            self.add_coupling(self.train_scheduler.output["train_arrival"], self.train_queue.input["train_arrival"])

        # Passenger generators to station queues
        for i in range(1, 6):
            self.add_coupling(self.passenger_generators[i-1].output["passenger_generated"], self.station_queues[i-1].input["passenger_generated"])

        # Station queues to train queue
        for i in range(1, 6):
            self.add_coupling(self.station_queues[i-1].output["passenger_boarding"], self.train_queue.input["passenger_boarding"])

        # Train queue to station queues (for alighting)
        # This is handled implicitly through train_arrival events

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=str, default="00:01:00:000")
    args = parser.parse_args()

    # Parse simulate_time
    try:
        h, m, s, ms = map(int, args.simulate_time.split(":"))
        simulate_time = h * 3600 + m * 60 + s + ms / 1000.0
    except Exception as e:
        print(f"Error parsing simulate_time: {e}", file=sys.stderr)
        sys.exit(1)

    # Create system
    root = OTrainSystem(simulate_time=simulate_time)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(simulate_time)

if __name__ == "__main__":
    main()