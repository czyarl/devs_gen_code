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

# Route sequence for the train
TRAIN_ROUTE = [
    (1, 0), (2, 0), (3, 0), (4, 0), (5, 1), (4, 1), (3, 1), (2, 1), (1, 0)
]

# Simulation parameters
TRAIN_TRAVEL_TIME = 225  # seconds between stations
INITIAL_PASSENGER_TIME = 0.5  # seconds
PASSENGER_GENERATION_MEAN = 5.0 * 60  # 5 minutes in seconds
PASSENGER_GENERATION_STD = 5.0 * 60  # 5 minutes in seconds
BOARDING_ALIGHTING_DELAY = 0.025  # seconds

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
        self.current_direction = 0
        self.passenger_count = 0
        
    def run(self):
        """Main train operation loop"""
        # Initial arrival at Bayview (station 1, direction 0)
        yield self.env.timeout(0)
        yield self.env.process(self._handle_train_arrival())
        
        # Continue the route
        for station_id, direction in TRAIN_ROUTE[1:]:
            # Travel time between stations
            yield self.env.timeout(TRAIN_TRAVEL_TIME)
            
            self.current_station = station_id
            self.current_direction = direction
            yield self.env.process(self._handle_train_arrival())
    
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
                "direction": self.current_direction
            }
        }
        print(json.dumps(event), file=sys.stdout)
        
        # Handle boarding passengers
        yield self.env.process(self._handle_boarding())
        
        # Handle alighting passengers
        yield self.env.process(self._handle_alighting())
    
    def _handle_boarding(self):
        """Handle passengers boarding the train"""
        queue = self.station_queues[self.current_station]
        passengers_to_board = []
        
        # Get passengers from the queue (FIFO)
        while queue and len(passengers_to_board) < 10:  # Max 10 passengers per station
            passenger = queue.popleft()
            passengers_to_board.append(passenger)
            
        # Process boarding one by one
        for i, passenger in enumerate(passengers_to_board):
            # Delay for boarding
            yield self.env.timeout(i * BOARDING_ALIGHTING_DELAY)
            
            # Log boarding event
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
            
            # Add to train queue
            self.train_queue[passenger.destination].append(passenger)
    
    def _handle_alighting(self):
        """Handle passengers alighting from the train"""
        # Get passengers destined for this station
        passengers_to_alight = []
        for passenger in list(self.train_queue[self.current_station]):
            passengers_to_alight.append(passenger)
            self.train_queue[self.current_station].remove(passenger)
        
        # Process alighting one by one
        for i, passenger in enumerate(passengers_to_alight):
            # Delay for alighting
            yield self.env.timeout(i * BOARDING_ALIGHTING_DELAY)
            
            # Log alighting event
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

class PassengerGenerator:
    """Generates passengers at each station"""
    def __init__(self, env, station_queues, passenger_counter):
        self.env = env
        self.station_queues = station_queues
        self.passenger_counter = passenger_counter
        
    def run(self):
        """Generate passengers at each station"""
        # Generate initial passengers at t=0.5
        yield self.env.timeout(INITIAL_PASSENGER_TIME)
        for station_id in range(1, 6):
            # Create initial passenger with ID=0
            passenger = Passenger(0, 0, station_id, 0)  # Destination will be set later
            self.station_queues[station_id].append(passenger)
            
            # Log initial passenger event
            event = {
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
            print(json.dumps(event), file=sys.stdout)
        
        # Generate regular passengers for each station
        for station_id in range(1, 6):
            # Start a separate process for each station's passenger generation
            yield self.env.process(self._generate_passengers_for_station(station_id))
    
    def _generate_passengers_for_station(self, station_id):
        """Generate passengers for a specific station"""
        while True:
            # Generate interval using normal distribution
            interval = random.normalvariate(PASSENGER_GENERATION_MEAN, PASSENGER_GENERATION_STD)
            # Clamp to [1, 9] minutes
            interval = max(60, min(540, interval))
            interval = round(interval)  # Round to nearest second
            
            # Wait for the interval
            yield self.env.timeout(interval)
            
            # Generate passenger
            self.passenger_counter[station_id] += 1
            passenger_num = self.passenger_counter[station_id]
            
            # Select destination (different from origin)
            destinations = [i for i in range(1, 6) if i != station_id]
            destination = random.choice(destinations)
            
            # Create passenger ID
            passenger_id = passenger_num * 100 + station_id * 10 + destination
            
            # Create passenger
            passenger = Passenger(passenger_id, passenger_num, station_id, destination)
            self.station_queues[station_id].append(passenger)
            
            # Log passenger generation event
            event = {
                "time": self.env.now,
                "event": "passenger_generated",
                "entity_type": "passenger_generator",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": {
                    "passenger_id": passenger_id,
                    "passenger_num": passenger_num,
                    "origin": station_id,
                    "destination": destination
                }
            }
            print(json.dumps(event), file=sys.stdout)

def main():
    """Main simulation function"""
    parser = argparse.ArgumentParser(description='O-Train Light Rail Simulation')
    parser.add_argument('--simulate_time', type=str, default='00:01:00:000',
                        help='Simulation duration in HH:MM:SS:mmm format')
    
    args = parser.parse_args()
    
    # Parse simulation time
    try:
        hours, minutes, seconds, milliseconds = map(int, args.simulate_time.split(':'))
        simulate_time = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    except ValueError:
        print("Invalid simulate_time format. Using default 1 minute.", file=sys.stderr)
        simulate_time = 60
    
    # Set up logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Initialize data structures
    station_queues = {i: collections.deque() for i in range(1, 6)}
    train_queue = {i: collections.deque() for i in range(1, 6)}
    passenger_counter = {i: 0 for i in range(1, 6)}
    
    # Create components
    train = Train(env, station_queues, train_queue)
    passenger_generator = PassengerGenerator(env, station_queues, passenger_counter)
    
    # Start simulation processes
    env.process(train.run())
    env.process(passenger_generator.run())
    
    # Run simulation
    try:
        env.run(until=simulate_time)
    except Exception as e:
        print(f"Simulation error: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Print final state
    final_state = {
        "time": env.now,
        "event": "simulation_end",
        "entity_type": "system",
        "station_id": 0,
        "station": "System",
        "payload": {
            "simulation_time": simulate_time,
            "passenger_count": sum(passenger_counter.values())
        }
    }
    print(json.dumps(final_state), file=sys.stdout)

if __name__ == "__main__":
    main()