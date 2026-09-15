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
STATIONS = {1: "Bayview", 2: "Carling", 3: "Carleton", 4: "Confed", 5: "Greenboro"}
STATION_IDS = {v: k for k, v in STATIONS.items()}
DIRECTIONS = {0: "Southbound", 1: "Northbound"}

# Passenger Generation
class PassengerGenerator:
    def __init__(self, env, station_id):
        self.env = env
        self.station_id = station_id
        self.passenger_num = 0
        self.process = env.process(self.generate_passengers())

    def generate_passengers(self):
        # Initial passenger at t=0.5
        at_initialization_time = 0.5
        if self.env.now >= at_initialization_time:
            yield self.env.timeout(at_initialization_time - self.env.now)
            passenger_id = 0
            origin = self.station_id
            destination = random.choice([i for i in STATION_IDS if i != origin])
            self.env.process(self.create_passenger_event(passenger_id, origin, destination))
        
        while True:
            interval = max(1, min(9, random.normalvariate(5*60, 5*60))) # Normal Distribution (Mean=5.0 min, Std=5.0 min)
            interval = round(interval * 60) # Convert to seconds and round to nearest integer
            yield self.env.timeout(interval)
            self.passenger_num += 1
            origin = self.station_id
            destination = random.choice([i for i in STATION_IDS if i != origin])
            passenger_id = self.passenger_num * 100 + origin * 10 + destination
            self.env.process(self.create_passenger_event(passenger_id, origin, destination))

    def create_passenger_event(self, passenger_id, origin, destination):
        event_time = self.env.now
        event = "passenger_generated"
        entity_type = "passenger_generator"
        station_id = origin
        station = STATIONS[station_id]
        payload = {
            "passenger_id": passenger_id,
            "passenger_num": self.passenger_num,
            "origin": origin,
            "destination": destination
        }
        self.env.process(self.write_event(event_time, event, entity_type, station_id, station, payload))

# Train Operations
class Train:
    def __init__(self, env):
        self.env = env
        self.station_sequence = [1, 2, 3, 4, 5, 4, 3, 2, 1]
        self.direction = 0
        self.current_station_index = 0
        self.process = env.process(self.move_train())

    def move_train(self):
        current_station_id = self.station_sequence[self.current_station_index]
        while True:
            event_time = self.env.now
            event = "train_arrival"
            entity_type = "train"
            station_id = current_station_id
            station = STATIONS[station_id]
            payload = {
                "station": station_id,
                "direction": self.direction
            }
            self.env.process(self.write_event(event_time, event, entity_type, station_id, station, payload))
            # Boarding and Alighting logic will be triggered here
            yield self.env.timeout(225)

            # Update train position
            self.current_station_index = (self.current_station_index + 1) % len(self.station_sequence)
            current_station_id = self.station_sequence[self.current_station_index]
            if self.current_station_index == len(self.station_sequence) // 2:
                self.direction = 1
            elif self.current_station_index == 0:
                self.direction = 0

    def write_event(self, event_time, event, entity_type, station_id, station, payload):
        print(json.dumps({
            "time": event_time,
            "event": event,
            "entity_type": entity_type,
            "station_id": station_id,
            "station": station,
            "payload": payload
        }))

# Station Queue and Boarding Logic
class StationQueue:
    def __init__(self, env, station_id):
        self.env = env
        self.station_id = station_id
        self.queue = []
        self.process = env.process(self.board_passengers())

    def board_passengers(self):
        while True:
            # Wait for train arrival
            yield self.env.timeout(0.1) # Check every 0.1 seconds

# Main
def main():
    parser = argparse.ArgumentParser(description='O-Train Light Rail Simulation')
    parser.add_argument('--simulate_time', type=str, default="00:01:00:000")
    args = parser.parse_args()

    hours, minutes, seconds, milliseconds = map(int, args.simulate_time.split(':'))
    simulate_time = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000

    env = simpy.Environment()
    logging.basicConfig(stream=sys.stderr)

    random.seed(time.time_ns())
    passenger_generators = [PassengerGenerator(env, station_id) for station_id in STATIONS]
    train = Train(env)

    def run_simulation():
        try:
            env.run(until=simulate_time)
        except Exception as e:
            logging.error(f"Simulation error: {e}")

    run_simulation()

if __name__ == "__main__":
    main()
</python_code>