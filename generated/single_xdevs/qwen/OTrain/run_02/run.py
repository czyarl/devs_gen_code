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

# Set random seed based on system time
random.seed(time.time_ns())
numpy_random_seed = time.time_ns() % (2**32 - 1)
try:
    import numpy as np
    np.random.seed(numpy_random_seed)
except ImportError:
    pass  # numpy not available, but we already have python random

# Station names mapping
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

# Train route
TRAIN_ROUTE = [
    (1, SOUTHBOUND),  # Bayview -> Southbound
    (2, SOUTHBOUND),
    (3, SOUTHBOUND),
    (4, SOUTHBOUND),
    (5, NORTHBOUND),  # Greenboro -> Northbound
    (4, NORTHBOUND),
    (3, NORTHBOUND),
    (2, NORTHBOUND),
    (1, SOUTHBOUND)   # Bayview -> Southbound (loop)
]

# Convert time string to seconds
def parse_time(time_str):
    h, m, s, ms = map(int, time_str.split(":"))
    return h * 3600 + m * 60 + s + ms / 1000.0

# Event output function
def output_event(event_type, entity_type, station_id, payload, time_val):
    event = {
        "time": time_val,
        "event": event_type,
        "entity_type": entity_type,
        "station_id": station_id,
        "station": STATIONS[station_id],
        "payload": payload
    }
    print(json.dumps(event), file=sys.stdout, flush=True)

class PassengerGenerator(Atomic):
    def __init__(self, name, parent, station_id):
        super().__init__(name)
        self.parent = parent
        self.station_id = station_id
        self.passenger_num = 0
        self.next_generation_time = 0.0
        self.passenger_queue = deque()
        self.add_in_port(Port(object, "train_arrival"))
        self.add_out_port(Port(object, "passenger_generated"))

    def initialize(self):
        # Generate initial passenger at t=0.5
        payload = {
            "passenger_id": 0,
            "passenger_num": 0,
            "origin": self.station_id,
            "destination": 0  # Will be set by the system
        }
        output_event("passenger_generated", "passenger_generator", self.station_id, payload, 0.5)
        self.passenger_num += 1
        self.hold_in("GENERATE", 0.5)

    def lambdaf(self):
        if self.passenger_queue:
            passenger = self.passenger_queue.popleft()
            self.output["passenger_generated"].add(passenger)

    def deltint(self):
        # Generate next passenger
        interval = random.normalvariate(5.0 * 60, 5.0 * 60)
        interval = max(1*60, min(9*60, interval))  # Clamp to [1, 9] minutes
        interval = round(interval)  # Round to nearest second
        self.next_generation_time += interval
        self.passenger_num += 1
        # Create passenger
        destinations = [i for i in range(1, 6) if i != self.station_id]
        dest = random.choice(destinations)
        payload = {
            "passenger_id": self.passenger_num * 100 + self.station_id * 10 + dest,
            "passenger_num": self.passenger_num,
            "origin": self.station_id,
            "destination": dest
        }
        self.passenger_queue.append(payload)
        self.hold_in("GENERATE", interval)

    def deltext(self, e):
        # Handle train arrival - we don't do anything here
        self.hold_in("GENERATE", 0)

    def exit(self):
        pass

class StationQueue(Atomic):
    def __init__(self, name, parent, station_id):
        super().__init__(name)
        self.parent = parent
        self.station_id = station_id
        self.passenger_queue = deque()
        self.add_in_port(Port(object, "passenger_generated"))
        self.add_in_port(Port(object, "train_arrival"))
        self.add_out_port(Port(object, "passenger_boarding"))

    def initialize(self):
        self.hold_in("WAIT", 0)

    def lambdaf(self):
        if self.passenger_queue:
            passenger = self.passenger_queue.popleft()
            self.output["passenger_boarding"].add(passenger)

    def deltint(self):
        self.hold_in("WAIT", 0)

    def deltext(self, e):
        if e == "passenger_generated":
            # Add passenger to queue
            for val in self.input["passenger_generated"].values:
                self.passenger_queue.append(val)
        elif e == "train_arrival":
            # Board passengers
            boarding_time = 0.025
            while self.passenger_queue:
                passenger = self.passenger_queue.popleft()
                output_event("passenger_boarding", "station_queue", self.station_id, passenger, self.get_time() + boarding_time)
                boarding_time += 0.025
        self.hold_in("WAIT", 0)

    def exit(self):
        pass

class TrainQueue(Atomic):
    def __init__(self, name, parent, station_id):
        super().__init__(name)
        self.parent = parent
        self.station_id = station_id
        self.passengers = []
        self.add_in_port(Port(object, "train_arrival"))
        self.add_out_port(Port(object, "passenger_exiting"))

    def initialize(self):
        self.hold_in("WAIT", 0)

    def lambdaf(self):
        # Nothing to output in lambdaf
        pass

    def deltint(self):
        self.hold_in("WAIT", 0)

    def deltext(self, e):
        if e == "train_arrival":
            # Alight passengers destined for this station
            alighting_time = 0.025
            passengers_to_remove = []
            for passenger in self.passengers:
                if passenger["destination"] == self.station_id:
                    output_event("passenger_exiting", "train_queue", self.station_id, passenger, self.get_time() + alighting_time)
                    alighting_time += 0.025
                    passengers_to_remove.append(passenger)
            for p in passengers_to_remove:
                self.passengers.remove(p)
        self.hold_in("WAIT", 0)

    def exit(self):
        pass

class Train(Atomic):
    def __init__(self, name, parent):
        super().__init__(name)
        self.parent = parent
        self.current_station_index = 0
        self.current_station = TRAIN_ROUTE[0][0]
        self.direction = TRAIN_ROUTE[0][1]
        self.next_arrival_time = 0.0
        self.add_out_port(Port(object, "train_arrival"))
        self.add_in_port(Port(object, "passenger_boarding"))
        self.add_in_port(Port(object, "passenger_exiting"))

    def initialize(self):
        self.next_arrival_time = 0.0
        payload = {
            "station": self.current_station,
            "direction": self.direction
        }
        output_event("train_arrival", "train", self.current_station, payload, 0.0)
        self.hold_in("WAIT", 225.0)  # First travel time

    def lambdaf(self):
        # Nothing to output in lambdaf
        pass

    def deltint(self):
        # Move to next station
        self.current_station_index = (self.current_station_index + 1) % len(TRAIN_ROUTE)
        self.current_station = TRAIN_ROUTE[self.current_station_index][0]
        self.direction = TRAIN_ROUTE[self.current_station_index][1]
        self.next_arrival_time += 225.0
        payload = {
            "station": self.current_station,
            "direction": self.direction
        }
        output_event("train_arrival", "train", self.current_station, payload, self.next_arrival_time)
        self.hold_in("WAIT", 225.0)

    def deltext(self, e):
        # No external transitions
        self.hold_in("WAIT", 0)

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name, parent, simulate_time):
        super().__init__(name)
        self.parent = parent
        self.simulate_time = simulate_time

        # Create components
        self.train = Train(name="train", parent=self)
        self.generators = [PassengerGenerator(name=f"generator_{i}", parent=self, station_id=i) for i in range(1, 6)]
        self.queues = [StationQueue(name=f"queue_{i}", parent=self, station_id=i) for i in range(1, 6)]
        self.train_queues = [TrainQueue(name=f"train_queue_{i}", parent=self, station_id=i) for i in range(1, 6)]

        # Add components
        self.add_component(self.train)
        for gen in self.generators:
            self.add_component(gen)
        for queue in self.queues:
            self.add_component(queue)
        for tq in self.train_queues:
            self.add_component(tq)

        # Define couplings
        # Train to all station queues
        for i in range(1, 6):
            self.add_coupling(self.train.output["train_arrival"], self.queues[i-1].input["train_arrival"])
            self.add_coupling(self.train.output["train_arrival"], self.train_queues[i-1].input["train_arrival"])

        # Passenger generator to station queues
        for i in range(1, 6):
            self.add_coupling(self.generators[i-1].output["passenger_generated"], self.queues[i-1].input["passenger_generated"])

        # Station queues to train queues
        for i in range(1, 6):
            self.add_coupling(self.queues[i-1].output["passenger_boarding"], self.train_queues[i-1].input["passenger_boarding"])

        # Train queues to train
        for i in range(1, 6):
            self.add_coupling(self.train_queues[i-1].output["passenger_exiting"], self.train.input["passenger_exiting"])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", type=str, default="00:01:00:000")
    args = parser.parse_args()

    simulate_time = parse_time(args.simulate_time)
    root = System(name="system", parent=None, simulate_time=simulate_time)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(simulate_time)

if __name__ == "__main__":
    main()