```python
import argparse
import sys
import json
import logging
import random
import time
import math
import simpy
from collections import deque
from typing import List, Dict, Any, Tuple

# Set seed for reproducibility
random.seed(time.time_ns())

# Station configuration
STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro"
}

# Route configuration
ROUTE = [
    (1, 0), (2, 0), (3, 0), (4, 0), (5, 1),
    (4, 1), (3, 1), (2, 1), (1, 0)
]

# Simulation parameters
TRAIN_TRAVEL_TIME = 225.0  # seconds between consecutive stations
INITIAL_PASSENGER_TIME = 0.5  # seconds
PASSENGER_GENERATION_INTERVAL_MEAN = 5.0 * 60  # 5 minutes in seconds
PASSENGER_GENERATION_INTERVAL_STD = 5.0 * 60  # 5 minutes in seconds
PASSENGER_BOARDING_ALIGHTING_DELAY = 0.025  # seconds

class Passenger:
    def __init__(self, passenger_id: int, passenger_num: int, origin: int, destination: int):
        self.passenger_id = passenger_id
        self.passenger_num = passenger_num
        self.origin = origin
        self.destination = destination

class Train:
    def __init__(self, env: simpy.Environment):
        self.env = env
        self.position = 0  # Current index in the route
        self.direction = 0  # 0 = Southbound, 1 = Northbound
        self.passengers = []  # List of passengers currently on the train
        self.current_station = ROUTE[0][0]
        self.current_direction = ROUTE[0][1]
        
    def move(self, station_id: int, direction: int):
        self.current_station = station_id
        self.current_direction = direction
        self.position = next(i for i, (s, d) in enumerate(ROUTE) if s == station_id and d == direction)
        
    def get_passengers_for_station(self, station_id: int) -> List[Passenger]:
        return [p for p in self.passengers if p.destination == station_id]
    
    def remove_passengers_for_station(self, station_id: int) -> List[Passenger]:
        passengers_to_remove = [p for p in self.passengers if p.destination == station_id]
        self.passengers = [p for p in self.passengers if p.destination != station_id]
        return passengers_to_remove

class StationQueue:
    def __init__(self, env: simpy.Environment, station_id: int):
        self.env = env
        self.station_id = station_id
        self.passengers = deque()
        self.passenger_counter = 0
        
    def add_passenger(self, passenger: Passenger):
        self.passengers.append(passenger)
        self.passenger_counter += 1
        
    def get_passenger(self) -> Passenger:
        if self.passengers:
            return self.passengers.popleft()
        return None

class PassengerGenerator:
    def __init__(self, env: simpy.Environment, station_id: int):
        self.env = env
        self.station_id = station_id
        self.passenger_counter = 0
        
    def generate_passenger(self, station_queue: StationQueue):
        # Create a new passenger
        self.passenger_counter += 1
        # Destination must be different from origin
        destinations = [i for i in range(1, 6) if i != self.station_id]
        destination = random.choice(destinations)
        passenger_id = self.passenger_counter * 100 + self.station_id * 10 + destination
        passenger = Passenger(passenger_id, self.passenger_counter, self.station_id, destination)
        station_queue.add_passenger(passenger)
        return passenger

class OTrainSimulation:
    def __init__(self, simulate_time: float):
        self.env = simpy.Environment()
        self.simulate_time = simulate_time
        self.train = Train(self.env)
        self.station_queues = {i: StationQueue(self.env, i) for i in range(1, 6)}
        self.passenger_generators = {i: PassengerGenerator(self.env, i) for i in range(1, 6)}
        self.next_passenger_id = 1
        self.events = []
        
    def run(self):
        # Schedule initial passengers
        for station_id in range(1, 6):
            self.env.process(self.schedule_initial_passenger(station_id))
            
        # Schedule passenger generation
        for station_id in range(1, 6):
            self.env.process(self.schedule_passenger_generation(station_id))
            
        # Schedule train movement
        self.env.process(self.schedule_train_movement())
        
        # Run simulation
        self.env.run(until=self.simulate_time)
        
        # Output all events
        for event in self.events:
            print(json.dumps(event))
            
    def schedule_initial_passenger(self, station_id: int):
        yield self.env.timeout(INITIAL_PASSENGER_TIME)
        passenger = Passenger(0, 0, station_id, 0)
        self.station_queues[station_id].add_passenger(passenger)
        self.log_event("passenger_generated", {
            "passenger_id": 0,
            "passenger_num": 0,
            "origin": station_id,
            "destination": 0
        }, station_id)
        
    def schedule_passenger_generation(self, station_id: int):
        while True:
            # Generate interval using normal distribution, clamped to [1, 9] minutes
            interval = random.normalvariate(PASSENGER_GENERATION_INTERVAL_MEAN, PASSENGER_GENERATION_INTERVAL_STD)
            interval = max(60, min(540, interval))  # Clamp to [1, 9] minutes
            interval = round(interval)  # Round to nearest second
            
            yield self.env.timeout(interval)
            
            # Generate passenger
            passenger = self.passenger_generators[station_id].generate_passenger(self.station_queues[station_id])
            self.log_event("passenger_generated", {
                "passenger_id": passenger.passenger_id,
                "passenger_num": passenger.passenger_num,
                "origin": passenger.origin,
                "destination": passenger.destination
            }, station_id)
            
    def schedule_train_movement(self):
        current_time = 0.0
        while current_time < self.simulate_time:
            # Determine next station and direction
            station_id, direction = ROUTE[self.train.position]
            
            # Schedule train arrival
            yield self.env.timeout(TRAIN_TRAVEL_TIME)
            current_time += TRAIN_TRAVEL_TIME
            
            # Update train position
            self.train.move(station_id, direction)
            
            # Log train arrival
            self.log_event("train_arrival", {
                "station": station_id,
                "direction": direction
            }, station_id)
            
            # Handle boarding
            self.env.process(self.handle_boarding(station_id, direction))
            
            # Handle alighting
            self.env.process(self.handle_alighting(station_id))
            
    def handle_boarding(self, station_id: int, direction: int):
        # Get passengers from queue
        passengers_to_board = []
        while len(passengers_to_board) < 100 and self.station_queues[station_id].passengers:
            passenger = self.station_queues[station_id].get_passenger()
            if passenger and passenger.origin == station_id:
                passengers_to_board.append(passenger)
                
        # Process boarding one by one
        boarding_time = 0.0
        for passenger in passengers_to_board:
            boarding_time += PASSENGER_BOARDING_ALIGHTING_DELAY
            yield self.env.timeout(boarding_time)
            self.train.passengers.append(passenger)
            self.log_event("passenger_boarding", {
                "passenger_id": passenger.passenger_id,
                "passenger_num": passenger.passenger_num,
                "origin": passenger.origin,
                "destination": passenger.destination
            }, station_id)
            
    def handle_alighting(self, station_id: int):
        # Get passengers to alight
        passengers_to_alight = self.train.remove_passengers_for_station(station_id)
        
        # Process alighting one by one
        alighting_time = 0.0
        for passenger in passengers_to_alight:
            alighting_time += PASSENGER_BOARDING_ALIGHTING_DELAY
            yield self.env.timeout(alighting_time)
            self.log_event("passenger_exiting", {
                "passenger_id": passenger.passenger_id,
                "passenger_num": passenger.passenger_num,
                "origin": passenger.origin,
                "destination": passenger.destination
            }, station_id)
            
    def log_event(self, event_type: str, payload: Dict[str, Any], station_id: int):
        event = {
            "time": round(self.env.now, 3),
            "event": event_type,
            "entity_type": self.get_entity_type(event_type),
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": payload
        }
        self.events.append(event)
        
    def get_entity_type(self, event_type: str) -> str:
        if event_type == "passenger_generated":
            return "passenger_generator"
        elif event_type == "train_arrival":
            return "train"
        elif event_type == "passenger_boarding":
            return "station_queue"
        elif event_type == "passenger_exiting":
            return "train_queue"
        return "unknown"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulate_time", default="00:01:00:000", help="Simulation duration in HH:MM:SS:mmm")
    
    args = parser.parse_args()
    
    # Parse simulate_time
    time_parts = args.simulate_time.split(":")
    hours = int(time_parts[0])
    minutes = int(time_parts[1])
    seconds = int(time_parts[2])
    milliseconds = int(time_parts[3])
    
    simulate_time = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    
    # Run simulation
    sim = OTrainSimulation(simulate_time)
    sim.run()

if __name__ == "__main__":
    main()
</python_code>