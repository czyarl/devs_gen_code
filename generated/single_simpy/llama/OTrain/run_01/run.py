```python
import argparse
import sys
import json
import logging
import random
import simpy
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

# Logging setup
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

def parse_args():
    parser = argparse.ArgumentParser(description='O-Train Light Rail Simulation')
    parser.add_argument('--simulate_time', type=str, default="00:01:00:000")
    args = parser.parse_args()
    hours, minutes, seconds, milliseconds = map(int, args.simulate_time.split(':'))
    total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    return total_seconds

class Passenger:
    def __init__(self, passenger_id, origin, destination):
        self.passenger_id = passenger_id
        self.origin = origin
        self.destination = destination

class Train:
    def __init__(self, env):
        self.env = env
        self.passengers = []
        self.direction = 0
        self.current_station = 1

    def move(self):
        stations = [1, 2, 3, 4, 5, 4, 3, 2]
        directions = [0, 0, 0, 0, 1, 1, 1, 1]
        while True:
            station = stations[self.current_station]
            direction = directions[self.current_station]
            self.current_station = (self.current_station + 1) % len(stations)
            yield self.env.timeout(225)
            self.direction = direction
            self.arrive(station)

    def arrive(self, station):
        print(json.dumps({
            "time": self.env.now,
            "event": "train_arrival",
            "entity_type": "train",
            "station_id": station,
            "station": STATIONS[station],
            "payload": {
                "station": station,
                "direction": self.direction
            }
        }))

        # Alight passengers
        alighting_passengers = [p for p in self.passengers if p.destination == station]
        for p in alighting_passengers:
            self.passengers.remove(p)
            print(json.dumps({
                "time": self.env.now,
                "event": "passenger_exiting",
                "entity_type": "train_queue",
                "station_id": station,
                "station": STATIONS[station],
                "payload": {
                    "passenger_id": p.passenger_id,
                    "passenger_num": p.passenger_id // 100,
                    "origin": p.origin,
                    "destination": p.destination
                }
            }))

        # Board passengers
        boarding_passengers = station_queue[station].copy()
        for p in boarding_passengers:
            if p.destination != station:
                self.passengers.append(p)
                station_queue[station].remove(p)
                print(json.dumps({
                    "time": self.env.now + (len(boarding_passengers) - 1) * 0.025,
                    "event": "passenger_boarding",
                    "entity_type": "station_queue",
                    "station_id": station,
                    "station": STATIONS[station],
                    "payload": {
                        "passenger_id": p.passenger_id,
                        "passenger_num": p.passenger_id // 100,
                        "origin": p.origin,
                        "destination": p.destination
                    }
                }))

class PassengerGenerator:
    def __init__(self, env, station):
        self.env = env
        self.station = station
        self.passenger_num = 0
        self.generate_passenger()

    def generate_passenger(self):
        while True:
            self.passenger_num += 1
            destination = random.choice([s for s in range(1, 6) if s != self.station])
            passenger_id = self.passenger_num * 100 + self.station * 10 + destination
            p = Passenger(passenger_id, self.station, destination)
            print(json.dumps({
                "time": self.env.now,
                "event": "passenger_generated",
                "entity_type": "passenger_generator",
                "station_id": self.station,
                "station": STATIONS[self.station],
                "payload": {
                    "passenger_id": p.passenger_id,
                    "passenger_num": p.passenger_id // 100,
                    "origin": p.origin,
                    "destination": p.destination
                }
            }))
            interval = max(1, min(9, random.gauss(5, 5))) * 60
            interval = round(interval)
            yield self.env.timeout(interval)

def main():
    random.seed(time.time_ns())
    env = simpy.Environment()
    total_seconds = parse_args()

    station_queue = defaultdict(list)

    # Initialize station queues with initial passengers
    for station in range(1, 6):
        p = Passenger(0, station, random.choice([s for s in range(1, 6) if s != station]))
        print(json.dumps({
            "time": 0.5,
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": station,
            "station": STATIONS[station],
            "payload": {
                "passenger_id": p.passenger_id,
                "passenger_num": p.passenger_id // 100,
                "origin": p.origin,
                "destination": p.destination
            }
        }))
        station_queue[station].append(p)

    # Create passenger generators
    for station in range(1, 6):
        PassengerGenerator(env, station)

    train = Train(env)
    env.process(train.move())

    env.run(until=total_seconds)

if __name__ == "__main__":
    main()
</python_code>
```