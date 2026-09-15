#!/usr/bin/env python3
"""
O-Train Light Rail Simulation
"""

import argparse
import sys
import json
import logging
import random
import time
import simpy
from collections import defaultdict

# Set random seed using system time
random.seed(time.time_ns())

# Station configuration
STATIONS = {
    1: "Bayview",
    2: "Carling", 
    3: "Carleton",
    4: "Confed",
    5: "Greenboro"
}

# Train route sequence
TRAIN_ROUTE = [
    (1, 0), (2, 0), (3, 0), (4, 0), (5, 1), 
    (4, 1), (3, 1), (2, 1), (1, 0)
]

# Simulation parameters
TRAIN_TRAVEL_TIME = 225  # seconds between stations
INITIAL_PASSENGER_TIME = 0.5  # seconds
PASSENGER_GENERATION_MEAN = 5 * 60  # 5 minutes in seconds
PASSENGER_GENERATION_STD = 5 * 60  # 5 minutes in seconds
BOARDING_ALIGHTING_DELAY = 0.025  # seconds

def parse_time(time_str):
    """Parse time string in HH:MM:SS:mmm format to seconds"""
    h, m, s, ms = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s + ms / 1000

def generate_passenger_id(passenger_num, origin, destination):
    """Generate passenger ID using the specified formula"""
    if passenger_num == 0 and origin is not None and destination is not None:
        return 0
    return passenger_num * 100 + origin * 10 + destination

class Passenger:
    """Represents a passenger in the simulation"""
    def __init__(self, passenger_id, passenger_num, origin, destination):
        self.passenger_id = passenger_id
        self.passenger_num = passenger_num
        self.origin = origin
        self.destination = destination

class Train:
    """Represents the train in the simulation"""
    def __init__(self, env, station_queues, train_queue):
        self.env = env
        self.station_queues = station_queues
        self.train_queue = train_queue
        self.current_station = 1
        self.direction = 0  # 0 = Southbound, 1 = Northbound
        self.position = 0  # Position in the route (index)
        
    def move_to_next_station(self):
        """Move the train to the next station in the route"""
        # Update position in the route
        self.position = (self.position + 1) % len(TRAIN_ROUTE)
        self.current_station, self.direction = TRAIN_ROUTE[self.position]
        
    def run(self):
        """Main train operation loop"""
        # Initial arrival at Bayview (station 1, direction 0)
        yield self.env.timeout(0)
        self._handle_train_arrival()
        
        # Continue with the route
        while True:
            # Wait for travel time to next station
            yield self.env.timeout(TRAIN_TRAVEL_TIME)
            
            # Move to next station
            self.move_to_next_station()
            
            # Handle train arrival
            self._handle_train_arrival()
    
    def _handle_train_arrival(self):
        """Handle train arrival at a station"""
        # Log train arrival
        event = {
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
        print(json.dumps(event), file=sys.stdout)
        
        # Process boarding
        self._process_boarding()
        
        # Process alighting
        self._process_alighting()
    
    def _process_boarding(self):
        """Process passengers boarding the train"""
        # Get passengers waiting at this station
        passengers = self.station_queues[self.current_station].get_passengers()
        
        # Process each passenger boarding
        for i, passenger in enumerate(passengers):
            # Delay for boarding
            yield self.env.timeout(i * BOARDING_ALIGHTING_DELAY)
            
            # Log passenger boarding
            event = {
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
            print(json.dumps(event), file=sys.stdout)
            
            # Add passenger to train queue
            self.train_queue.add_passenger(passenger)
    
    def _process_alighting(self):
        """Process passengers alighting from the train"""
        # Get passengers destined for this station
        passengers = self.train_queue.get_passengers_for_station(self.current_station)
        
        # Process each passenger alighting
        for i, passenger in enumerate(passengers):
            # Delay for alighting
            yield self.env.timeout(i * BOARDING_ALIGHTING_DELAY)
            
            # Log passenger exiting
            event = {
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
            print(json.dumps(event), file=sys.stdout)
            
            # Remove passenger from train queue
            self.train_queue.remove_passenger(passenger)

class StationQueue:
    """Manages passengers waiting at a station to board the train"""
    def __init__(self, env, station_id):
        self.env = env
        self.station_id = station_id
        self.passengers = []
        self.passenger_counter = 0
        
    def add_passenger(self, passenger):
        """Add a passenger to the queue"""
        self.passengers.append(passenger)
        
    def get_passengers(self):
        """Get all passengers at this station"""
        # Return passengers who are at this station
        passengers_at_station = [p for p in self.passengers if p.origin == self.station_id]
        # Sort by arrival time (FIFO)
        passengers_at_station.sort(key=lambda p: p.passenger_num)
        return passengers_at_station
    
    def remove_passenger(self, passenger):
        """Remove a passenger from the queue"""
        if passenger in self.passengers:
            self.passengers.remove(passenger)

class TrainQueue:
    """Manages passengers currently on the train"""
    def __init__(self, env):
        self.env = env
        self.passengers = []
        self.passengers_by_destination = defaultdict(list)
        
    def add_passenger(self, passenger):
        """Add a passenger to the train"""
        self.passengers.append(passenger)
        self.passengers_by_destination[passenger.destination].append(passenger)
        
    def get_passengers_for_station(self, station_id):
        """Get passengers destined for a specific station"""
        return self.passengers_by_destination[station_id]
        
    def remove_passenger(self, passenger):
        """Remove a passenger from the train"""
        if passenger in self.passengers:
            self.passengers.remove(passenger)
            if passenger in self.passengers_by_destination[passenger.destination]:
                self.passengers_by_destination[passenger.destination].remove(passenger)

class PassengerGenerator:
    """Generates passengers at each station"""
    def __init__(self, env, station_queues, station_id):
        self.env = env
        self.station_queues = station_queues
        self.station_id = station_id
        self.passenger_counter = 0
        
    def generate_passenger(self):
        """Generate a new passenger at this station"""
        # Generate passenger ID
        passenger_id = generate_passenger_id(self.passenger_counter, self.station_id, None)
        
        # Generate destination (uniformly from other stations)
        destinations = [i for i in range(1, 6) if i != self.station_id]
        destination = random.choice(destinations)
        
        # Update passenger ID with destination
        passenger_id = generate_passenger_id(self.passenger_counter, self.station_id, destination)
        
        # Create passenger
        passenger = Passenger(passenger_id, self.passenger_counter, self.station_id, destination)
        
        # Add to station queue
        self.station_queues[self.station_id].add_passenger(passenger)
        
        # Log passenger generation
        event = {
            "time": self.env.now,
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": self.station_id,
            "station": STATIONS[self.station_id],
            "payload": {
                "passenger_id": passenger.passenger_id,
                "passenger_num": passenger.passenger_num,
                "origin": passenger.origin,
                "destination": passenger.destination
            }
        }
        print(json.dumps(event), file=sys.stdout)
        
        # Increment counter
        self.passenger_counter += 1
        
        return passenger

def main():
    """Main simulation function"""
    parser = argparse.ArgumentParser(description='O-Train Light Rail Simulation')
    parser.add_argument('--simulate_time', type=str, default='00:01:00:000',
                        help='Simulation duration in HH:MM:SS:mmm format')
    
    args = parser.parse_args()
    
    # Parse simulation time
    simulate_time = parse_time(args.simulate_time)
    
    # Set up logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create station queues
    station_queues = {i: StationQueue(env, i) for i in range(1, 6)}
    
    # Create train queue
    train_queue = TrainQueue(env)
    
    # Create train
    train = Train(env, station_queues, train_queue)
    
    # Create passenger generators for each station
    passenger_generators = {}
    for station_id in range(1, 6):
        passenger_generators[station_id] = PassengerGenerator(env, station_queues, station_id)
    
    # Initialize passengers at all stations at t=0.5
    for station_id in range(1, 6):
        env.process(initialize_passenger(env, passenger_generators[station_id], station_id))
    
    # Start passenger generation at each station
    for station_id in range(1, 6):
        env.process(generate_passengers(env, passenger_generators[station_id]))
    
    # Start train
    env.process(train.run())
    
    # Run simulation
    env.run(until=simulate_time)
    
def initialize_passenger(env, generator, station_id):
    """Initialize the special passenger at t=0.5"""
    yield env.timeout(INITIAL_PASSENGER_TIME)
    
    # Generate initial passenger with ID=0
    passenger_id = 0
    destinations = [i for i in range(1, 6) if i != station_id]
    destination = random.choice(destinations)
    
    passenger = Passenger(passenger_id, 0, station_id, destination)
    
    # Add to station queue
    generator.station_queues[station_id].add_passenger(passenger)
    
    # Log passenger generation
    event = {
        "time": env.now,
        "event": "passenger_generated",
        "entity_type": "passenger_generator",
        "station_id": station_id,
        "station": STATIONS[station_id],
        "payload": {
            "passenger_id": passenger.passenger_id,
            "passenger_num": passenger.passenger_num,
            "origin": passenger.origin,
            "destination": passenger.destination
        }
    }
    print(json.dumps(event), file=sys.stdout)

def generate_passengers(env, generator):
    """Generate passengers at regular intervals"""
    while True:
        # Generate interval using normal distribution
        interval = random.normalvariate(PASSENGER_GENERATION_MEAN, PASSENGER_GENERATION_STD)
        
        # Clamp interval to [1, 9] minutes
        interval = max(60, min(540, interval))  # 1 min = 60s, 9 min = 540s
        
        # Round to nearest integer seconds
        interval = round(interval)
        
        # Wait for the interval
        yield env.timeout(interval)
        
        # Generate passenger
        generator.generate_passenger()

if __name__ == "__main__":
    main()