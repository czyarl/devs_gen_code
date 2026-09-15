#!/usr/bin/env python3
"""
O-Train Light Rail Simulation
"""

import argparse
import sys
import json
import logging
import collections
import random
import time
import simpy

# Set up logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)

# Station configuration
STATIONS = {
    1: "Bayview",
    2: "Carling", 
    3: "Carleton",
    4: "Confed",
    5: "Greenboro"
}

# Route sequence for the train
TRAIN_ROUTE = [
    (1, 0), (2, 0), (3, 0), (4, 0), (5, 1), (4, 1), (3, 1), (2, 1), (1, 0)
]

# Set random seed using system time
random.seed(time.time_ns())

class Passenger:
    def __init__(self, passenger_id, passenger_num, origin, destination):
        self.passenger_id = passenger_id
        self.passenger_num = passenger_num
        self.origin = origin
        self.destination = destination

class Train:
    def __init__(self, env, station_queues, train_queue):
        self.env = env
        self.station_queues = station_queues
        self.train_queue = train_queue
        self.current_station = 1
        self.direction = 0  # 0 = Southbound, 1 = Northbound
        self.next_station_index = 0
        
    def move_train(self):
        """Move the train along the route"""
        while True:
            # Get next station and direction
            self.current_station, self.direction = TRAIN_ROUTE[self.next_station_index]
            
            # Report train arrival
            event_data = {
                "time": self.env.now,
                "event": "train_arrival",
                "entity_type": "train",
                "station_id": self.current_station,
                "station": STATIONS[self.current_station],
                "payload": {
                    "station": self.current_station,
                    "direction": self.direction
                }
            }
            print(json.dumps(event_data))
            
            # Process boarding and alighting
            yield self.env.process(self.process_boarding())
            yield self.env.process(self.process_alighting())
            
            # Move to next station
            self.next_station_index = (self.next_station_index + 1) % len(TRAIN_ROUTE)
            
            # Wait for travel time
            yield self.env.timeout(225.0)
    
    def process_boarding(self):
        """Process passengers boarding the train"""
        queue = self.station_queues[self.current_station]
        passengers_to_board = []
        
        # Get passengers from the queue who want to go in the same direction
        # and are not destined for this station
        while queue:
            passenger = queue.popleft()
            if passenger.destination == self.current_station:
                # Passenger is destined for this station, so they should alight here
                # We don't board them, they're already on the train
                queue.appendleft(passenger)  # Put them back
                break
            elif self.is_passenger_in_direction(passenger):
                # Board this passenger if they're going in the same direction
                passengers_to_board.append(passenger)
            else:
                # Passenger is going in the opposite direction, put them back
                queue.appendleft(passenger)
        
        # Board passengers one by one with 0.025s delay
        for i, passenger in enumerate(passengers_to_board):
            delay = 0.025 * i
            yield self.env.timeout(delay)
            
            # Report boarding event
            event_data = {
                "time": self.env.now,
                "event": "passenger_boarding",
                "entity_type": "station_queue",
                "station_id": self.current_station,
                "station": STATIONS[self.current_station],
                "payload": {
                    "passenger_id": passenger.passenger_id,
                    "passenger_num": passenger.passenger_num,
                    "origin": passenger.origin,
                    "destination": passenger.destination
                }
            }
            print(json.dumps(event_data))
            
            # Add to train queue
            self.train_queue[passenger.destination].append(passenger)
    
    def is_passenger_in_direction(self, passenger):
        """Check if passenger is going in the same direction as the train"""
        # For Southbound (0): passengers going to higher station IDs
        # For Northbound (1): passengers going to lower station IDs
        if self.direction == 0:  # Southbound
            return passenger.destination > self.current_station
        else:  # Northbound
            return passenger.destination < self.current_station
    
    def process_alighting(self):
        """Process passengers alighting from the train"""
        # Get passengers destined for this station
        passengers_to_alight = []
        while self.train_queue[self.current_station]:
            passenger = self.train_queue[self.current_station].popleft()
            passengers_to_alight.append(passenger)
        
        # Alight passengers one by one with 0.025s delay
        for i, passenger in enumerate(passengers_to_alight):
            delay = 0.025 * i
            yield self.env.timeout(delay)
            
            # Report alighting event
            event_data = {
                "time": self.env.now,
                "event": "passenger_exiting",
                "entity_type": "train_queue",
                "station_id": self.current_station,
                "station": STATIONS[self.current_station],
                "payload": {
                    "passenger_id": passenger.passenger_id,
                    "passenger_num": passenger.passenger_num,
                    "origin": passenger.origin,
                    "destination": passenger.destination
                }
            }
            print(json.dumps(event_data))

class PassengerGenerator:
    def __init__(self, env, station_queues, passenger_counter):
        self.env = env
        self.station_queues = station_queues
        self.passenger_counter = passenger_counter
        self.passenger_num = 0
        
    def generate_passengers(self, station_id):
        """Generate passengers at a station"""
        # Generate initial passenger at t=0.5
        if self.env.now == 0.5:
            passenger = Passenger(0, 0, station_id, 0)  # Special case for initial passenger
            self.station_queues[station_id].append(passenger)
            
            # Report passenger generation event
            event_data = {
                "time": self.env.now,
                "event": "passenger_generated",
                "entity_type": "passenger_generator",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": {
                    "passenger_id": 0,
                    "passenger_num": 0,
                    "origin": station_id,
                    "destination": 0
                }
            }
            print(json.dumps(event_data))
        
        # Generate regular passengers
        while True:
            # Calculate interval using normal distribution
            interval_minutes = random.normalvariate(5.0, 5.0)
            # Clamp to range [1, 9] minutes
            interval_minutes = max(1, min(9, interval_minutes))
            # Convert to seconds and round
            interval_seconds = round(interval_minutes * 60)
            
            # Wait for the interval
            yield self.env.timeout(interval_seconds)
            
            # Generate passenger with random destination (different from origin)
            destinations = [i for i in range(1, 6) if i != station_id]
            destination = random.choice(destinations)
            
            # Create passenger ID
            self.passenger_num += 1
            passenger_id = self.passenger_num * 100 + station_id * 10 + destination
            
            # Create passenger
            passenger = Passenger(passenger_id, self.passenger_num, station_id, destination)
            self.station_queues[station_id].append(passenger)
            
            # Report passenger generation event
            event_data = {
                "time": self.env.now,
                "event": "passenger_generated",
                "entity_type": "passenger_generator",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": {
                    "passenger_id": passenger_id,
                    "passenger_num": self.passenger_num,
                    "origin": station_id,
                    "destination": destination
                }
            }
            print(json.dumps(event_data))

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='O-Train Light Rail Simulation')
    parser.add_argument('--simulate_time', type=str, default='00:01:00:000',
                        help='Simulation duration in HH:MM:SS:mmm format')
    
    args = parser.parse_args()
    
    # Parse simulation time
    try:
        time_parts = args.simulate_time.split(':')
        hours = int(time_parts[0])
        minutes = int(time_parts[1])
        seconds = int(time_parts[2])
        milliseconds = int(time_parts[3])
        
        simulate_duration = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
    except (ValueError, IndexError):
        logging.error("Invalid simulate_time format. Using default 1 minute.")
        simulate_duration = 60.0
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Initialize data structures
    station_queues = {i: collections.deque() for i in range(1, 6)}
    train_queue = {i: collections.deque() for i in range(1, 6)}
    passenger_counter = 0
    
    # Create train
    train = Train(env, station_queues, train_queue)
    
    # Create passenger generators for each station
    generators = []
    for station_id in range(1, 6):
        generator = PassengerGenerator(env, station_queues, passenger_counter)
        generators.append(generator)
        env.process(generator.generate_passengers(station_id))
    
    # Start train movement
    env.process(train.move_train())
    
    # Run simulation for specified duration
    logging.info(f"Starting simulation for {simulate_duration} seconds")
    env.run(until=simulate_duration)
    
    logging.info("Simulation completed")

if __name__ == "__main__":
    main()