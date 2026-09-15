#!/usr/bin/env python3
"""
O-Train Light Rail Simulation
Simulates the Ottawa O-Train light rail system with a single train
shuttling passengers between 5 fixed stations.
"""

import argparse
import sys
import json
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

# Route sequence for the train
TRAIN_ROUTE = [
    (1, 0), (2, 0), (3, 0), (4, 0), (5, 1), 
    (4, 1), (3, 1), (2, 1), (1, 0)
]

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
        self.passenger_counter = 1  # Start from 1 for regular passengers
        
    def run(self):
        """Main train operation loop"""
        # Initial arrival at Bayview (station 1, direction 0) at time 0.0
        yield self.env.timeout(0.0)
        yield self.env.process(self.handle_station_arrival(1, 0))
        
        # Continue the route
        for station_id, direction in TRAIN_ROUTE[1:]:
            # Travel time between stations
            yield self.env.timeout(225.0)
            yield self.env.process(self.handle_station_arrival(station_id, direction))
    
    def handle_station_arrival(self, station_id, direction):
        """Handle train arrival at a station"""
        # Generate train arrival event
        event = {
            "time": self.env.now,
            "event": "train_arrival",
            "entity_type": "train",
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": {
                "station": station_id,
                "direction": direction
            }
        }
        print(json.dumps(event), file=sys.stdout)
        
        # Handle boarding passengers
        yield self.env.process(self.board_passengers(station_id))
        
        # Handle alighting passengers
        yield self.env.process(self.alight_passengers(station_id))
        
        # Update train state
        self.current_station = station_id
        self.current_direction = direction
    
    def board_passengers(self, station_id):
        """Handle passenger boarding at a station"""
        # Get passengers waiting at this station
        passengers = self.station_queues[station_id].get_passengers_for_boarding()
        
        # Board passengers one by one with 0.025s delay
        for i, passenger in enumerate(passengers):
            # Delay between boarding passengers
            if i > 0:
                yield self.env.timeout(0.025)
            
            # Generate boarding event
            event = {
                "time": self.env.now,
                "event": "passenger_boarding",
                "entity_type": "station_queue",
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
            
            # Add passenger to train queue
            self.train_queue.add_passenger(passenger)
    
    def alight_passengers(self, station_id):
        """Handle passenger alighting at a station"""
        # Get passengers destined for this station
        passengers = self.train_queue.get_passengers_for_alighting(station_id)
        
        # Alight passengers one by one with 0.025s delay
        for i, passenger in enumerate(passengers):
            # Delay between alighting passengers
            if i > 0:
                yield self.env.timeout(0.025)
            
            # Generate exiting event
            event = {
                "time": self.env.now,
                "event": "passenger_exiting",
                "entity_type": "train_queue",
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
            
            # Remove passenger from train queue
            self.train_queue.remove_passenger(passenger)

class StationQueue:
    """Manages passengers waiting at a station to board the train"""
    def __init__(self, station_id):
        self.station_id = station_id
        self.passengers = []  # FIFO queue
    
    def add_passenger(self, passenger):
        """Add a passenger to the queue"""
        self.passengers.append(passenger)
    
    def get_passengers_for_boarding(self):
        """Get passengers who can board at this station"""
        # Filter passengers who are waiting at this station
        boarding_passengers = [p for p in self.passengers if p.origin == self.station_id]
        # Remove them from the queue
        self.passengers = [p for p in self.passengers if p.origin != self.station_id]
        return boarding_passengers
    
    def get_passenger_count(self):
        """Get the number of passengers waiting at this station"""
        return len(self.passengers)

class TrainQueue:
    """Manages passengers currently on the train"""
    def __init__(self):
        self.passengers_by_destination = defaultdict(list)
    
    def add_passenger(self, passenger):
        """Add a passenger to the train"""
        self.passengers_by_destination[passenger.destination].append(passenger)
    
    def get_passengers_for_alighting(self, station_id):
        """Get passengers destined for this station"""
        passengers = self.passengers_by_destination[station_id]
        # Remove them from the queue
        self.passengers_by_destination[station_id] = []
        return passengers
    
    def remove_passenger(self, passenger):
        """Remove a passenger from the train"""
        if passenger.destination in self.passengers_by_destination:
            try:
                self.passengers_by_destination[passenger.destination].remove(passenger)
            except ValueError:
                pass  # Passenger not found, which is fine

class PassengerGenerator:
    """Generates passengers at each station"""
    def __init__(self, env, station_queues, train_queue):
        self.env = env
        self.station_queues = station_queues
        self.train_queue = train_queue
        self.passenger_counter = 1  # Start from 1 for regular passengers
    
    def generate_passengers(self):
        """Generate passengers at each station"""
        # Generate initial passengers at t=0.5
        yield self.env.timeout(0.5)
        for station_id in STATIONS:
            # Create initial passenger with ID=0
            passenger = Passenger(0, 0, station_id, station_id)
            self.station_queues[station_id].add_passenger(passenger)
            
            # Generate passenger generated event
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
                    "destination": station_id
                }
            }
            print(json.dumps(event), file=sys.stdout)
        
        # Generate regular passengers
        for station_id in STATIONS:
            yield self.env.process(self.generate_regular_passenger(station_id))
    
    def generate_regular_passenger(self, station_id):
        """Generate a regular passenger at a station"""
        while True:
            # Generate interval using normal distribution
            interval_minutes = random.normalvariate(5.0, 5.0)
            # Clamp to [1, 9] minutes
            interval_minutes = max(1.0, min(9.0, interval_minutes))
            # Convert to seconds and round
            interval_seconds = round(interval_minutes * 60)
            
            # Wait for the interval
            yield self.env.timeout(interval_seconds)
            
            # Generate destination (different from origin)
            destinations = [i for i in STATIONS if i != station_id]
            destination = random.choice(destinations)
            
            # Create passenger ID
            passenger_id = self.passenger_counter * 100 + station_id * 10 + destination
            
            # Create passenger
            passenger = Passenger(passenger_id, self.passenger_counter, station_id, destination)
            self.station_queues[station_id].add_passenger(passenger)
            
            # Generate passenger generated event
            event = {
                "time": self.env.now,
                "event": "passenger_generated",
                "entity_type": "passenger_generator",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": {
                    "passenger_id": passenger_id,
                    "passenger_num": self.passenger_counter,
                    "origin": station_id,
                    "destination": destination
                }
            }
            print(json.dumps(event), file=sys.stdout)
            
            # Increment counter
            self.passenger_counter += 1

def main():
    """Main simulation function"""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='O-Train Light Rail Simulation')
    parser.add_argument('--simulate_time', 
                       default='00:01:00:000',
                       help='Simulation duration in HH:MM:SS:mmm. Default: 00:01:00:000')
    
    args = parser.parse_args()
    
    # Parse simulate_time
    try:
        hours, minutes, seconds, milliseconds = map(int, args.simulate_time.split(':'))
        simulate_duration = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
    except ValueError:
        print("Invalid simulate_time format. Using default 1 minute.", file=sys.stderr)
        simulate_duration = 60.0
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create station queues
    station_queues = {i: StationQueue(i) for i in range(1, 6)}
    
    # Create train queue
    train_queue = TrainQueue()
    
    # Create train
    train = Train(env, station_queues, train_queue)
    
    # Create passenger generator
    passenger_generator = PassengerGenerator(env, station_queues, train_queue)
    
    # Start simulation processes
    env.process(train.run())
    env.process(passenger_generator.generate_passengers())
    
    # Run simulation for specified duration
    try:
        env.run(until=simulate_duration)
    except Exception as e:
        print(f"Simulation error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()