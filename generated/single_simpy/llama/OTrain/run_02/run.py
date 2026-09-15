```python
import argparse
import sys
import json
import logging
import random
import simpy
import numpy as np
import time
from collections import defaultdict

# Constants
STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro"
}

DIRECTIONS = {
    0: "Southbound",
    1: "Northbound"
}

ROUTE = [
    (1, 0), (2, 0), (3, 0), (4, 0), (5, 1),
    (4, 1), (3, 1), (2, 1), (1, 0)
]

class Passenger:
    def __init__(self, passenger_id, origin, destination):
        self.passenger_id = passenger_id
        self.origin = origin
        self.destination = destination

class Train:
    def __init__(self, env):
        self.env = env
        self.station_id = 1
        self.direction = 0
        self.passengers = []

    def move(self):
        while True:
            yield self.env.timeout(225)
            self.station_id, self.direction = ROUTE.pop(0)
            ROUTE.append((self.station_id, self.direction))
            print(json.dumps({
                "time": self.env.now,
                "event": "train_arrival",
                "entity_type": "train",
                "station_id": self.station_id,
                "station": STATIONS[self.station_id],
                "payload": {
                    "station": self.station_id,
                    "direction": self.direction
                }
            }))

def generate_passengers(env, station_id):
    passenger_num = 0
    while True:
        interval = max(1, min(9, np.random.normal(5, 5))) * 60
        interval = round(interval)
        yield env.timeout(interval)
        destination = random.randint(1, 5)
        while destination == station_id:
            destination = random.randint(1, 5)
        passenger_id = passenger_num * 100 + station_id * 10 + destination
        passenger_num += 1
        print(json.dumps({
            "time": env.now,
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": {
                "passenger_id": passenger_id,
                "passenger_num": passenger_num - 1,
                "origin": station_id,
                "destination": destination
            }
        }))

def initialize_passengers(env):
    for station_id in STATIONS.keys():
        print(json.dumps({
            "time": 0.5,
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": {
                "passenger_id": 0,
                "passenger_num": 0,
                "origin": station_id,
                "destination": random.randint(1, 5)
            }
        }))

def station_queue(env, train, station_id):
    queue = []
    while True:
        passenger = yield env.event
        if passenger.origin == station_id and passenger.destination != station_id:
            queue.append(passenger)
        if train.station_id == station_id:
            while queue:
                passenger = queue.pop(0)
                train.passengers.append(passenger)
                print(json.dumps({
                    "time": env.now,
                    "event": "passenger_boarding",
                    "entity_type": "station_queue",
                    "station_id": station_id,
                    "station": STATIONS[station_id],
                    "payload": {
                        "passenger_id": passenger.passenger_id,
                        "passenger_num": passenger.passenger_id // 100,
                        "origin": passenger.origin,
                        "destination": passenger.destination
                    }
                }))
                yield env.timeout(0.025)

def train_queue(env, train):
    while True:
        if train.station_id in [p.destination for p in train.passengers]:
            passengers_to_remove = [p for p in train.passengers if p.destination == train.station_id]
            for p in passengers_to_remove:
                train.passengers.remove(p)
                print(json.dumps({
                    "time": env.now,
                    "event": "passenger_exiting",
                    "entity_type": "train_queue",
                    "station_id": train.station_id,
                    "station": STATIONS[train.station_id],
                    "payload": {
                        "passenger_id": p.passenger_id,
                        "passenger_num": p.passenger_id // 100,
                        "origin": p.origin,
                        "destination": p.destination
                    }
                }))
                yield env.timeout(0.025)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", default="00:01:00:000")
    args = parser.parse_args()

    hours, minutes, seconds, milliseconds = map(int, args.simulate_time.split(':'))
    simulate_time = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000

    random.seed(time.time_ns())
    np.random.seed(time.time_ns() % (2**32 - 1))

    env = simpy.Environment()
    train = Train(env)

    for station_id in STATIONS.keys():
        env.process(generate_passengers(env, station_id))
    env.process(train.move())
    for station_id in STATIONS.keys():
        env.process(station_queue(env, train, station_id))
    env.process(train_queue(env, train))

    initialize_passengers(env)

    env.run(until=simulate_time)

if __name__ == "__main__":
    main()
</python_code>
```