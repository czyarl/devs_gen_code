import argparse
import sys
import json
import logging
import collections
import random
import simpy
import xdevs
import time

class OTrainSimulation:
    def __init__(self, env, simulate_time):
        self.env = env
        self.simulate_time = simulate_time
        self.stations = ["Bayview", "Carling", "Carleton", "Confed", "Greenboro"]
        self.train_direction = 0
        self.train_station = 0
        self.passenger_id = 0

    def run(self):
        logging.info("Simulation started.")
        self.train_arrival()
        self.passenger_generation()
        self.env.run(until=self.simulate_time)
        logging.info("Simulation ended.")

    def train_arrival(self):
        while True:
            self.env.process(self.train_move())
            yield self.env.timeout(225)

    def train_move(self):
        self.train_station = (self.train_station + 1) % 5
        self.train_direction = 1 if self.train_station == 4 else 0
        logging.info(f"Train arrived at {self.stations[self.train_station]}.")
        # Generate train arrival event
        event = {
            "time": self.env.now,
            "event": "train_arrival",
            "entity_type": "train",
            "station_id": self.train_station + 1,
            "station": self.stations[self.train_station],
            "payload": {
                "station": self.train_station + 1,
                "direction": self.train_direction
            }
        }
        print(json.dumps(event))

    def passenger_generation(self):
        while True:
            yield self.env.timeout(random.uniform(300, 540))
            origin = random.randint(0, 4)
            destination = random.randint(0, 4)
            while destination == origin:
                destination = random.randint(0, 4)
            self.passenger_id += 1
            logging.info(f"Passenger {self.passenger_id} generated at {self.stations[origin]}.")
            # Generate passenger generated event
            event = {
                "time": self.env.now,
                "event": "passenger_generated",
                "entity_type": "passenger_generator",
                "station_id": origin + 1,
                "station": self.stations[origin],
                "payload": {
                    "passenger_id": self.passenger_id,
                    "passenger_num": self.passenger_id,
                    "origin": origin + 1,
                    "destination": destination + 1
                }
            }
            print(json.dumps(event))