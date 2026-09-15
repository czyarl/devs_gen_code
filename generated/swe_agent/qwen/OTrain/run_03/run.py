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

# Route sequence (station_id, direction)
ROUTE = [
    (1, 0), (2, 0), (3, 0), (4, 0), (5, 1), 
    (4, 1), (3, 1), (2, 1), (1, 0)
]

# Travel time between stations in seconds
TRAVEL_TIME = 225

class Train:
    def __init__(self, env, station_queues, train_queue):
        self.env = env
        self.station_queues = station_queues
        self.train_queue = train_queue
        self.current_station = 1
        self.direction = 0  # 0 = Southbound, 1 = Northbound
        self.passenger_count = 0
        
        # Start the train movement process
        self.process = env.process(self.move_train())
    
    def move_train(self):
        """Move the train along the route"""
        # Initial position at Bayview (station 1, direction 0) at time 0.0
        yield self.env.timeout(0.0)
        
        while True:
            # Get current station and direction
            current_station_id, direction = self.get_current_position()
            
            # Generate train arrival event
            event_data = {
                "time": self.env.now,
                "event": "train_arrival",
                "entity_type": "train",
                "station_id": current_station_id,
                "station": STATIONS[current_station_id],
                "payload": {
                    "station": current_station_id,
                    "direction": direction
                }
            }
            print(json.dumps(event_data))
            
            # Process boarding and alighting
            yield self.env.process(self.handle_station(current_station_id, direction))
            
            # Move to next station
            next_station_id, next_direction = self.get_next_position()
            yield self.env.timeout(TRAVEL_TIME)
            
            self.current_station = next_station_id
            self.direction = next_direction
    
    def get_current_position(self):
        """Get current position based on current_station and direction"""
        return (self.current_station, self.direction)
    
    def get_next_position(self):
        """Get next position in the route"""
        # Find current position in route
        current_idx = ROUTE.index((self.current_station, self.direction))
        next_idx = (current_idx + 1) % len(ROUTE)
        return ROUTE[next_idx]
    
    def handle_station(self, station_id, direction):
        """Handle boarding and alighting at a station"""
        # Process alighting passengers
        yield self.env.process(self.process_alighting(station_id))
        
        # Process boarding passengers
        yield self.env.process(self.process_boarding(station_id))
    
    def process_alighting(self, station_id):
        """Process passengers alighting at the station"""
        # Get passengers destined for this station
        passengers_to_alight = []
        for passenger in list(self.train_queue):
            if passenger['destination'] == station_id:
                passengers_to_alight.append(passenger)
        
        # Remove passengers from train queue
        for passenger in passengers_to_alight:
            self.train_queue.remove(passenger)
        
        # Process alighting one by one with 0.025s delay
        for i, passenger in enumerate(passengers_to_alight):
            yield self.env.timeout(0.025 * i)
            
            # Generate passenger exiting event
            event_data = {
                "time": self.env.now,
                "event": "passenger_exiting",
                "entity_type": "train_queue",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": {
                    "passenger_id": passenger['id'],
                    "passenger_num": passenger['num'],
                    "origin": passenger['origin'],
                    "destination": passenger['destination']
                }
            }
            print(json.dumps(event_data))
    
    def process_boarding(self, station_id):
        """Process passengers boarding at the station"""
        # Get passengers waiting at this station
        passengers_to_board = []
        if station_id in self.station_queues:
            passengers_to_board = self.station_queues[station_id].get_passengers()
        
        # Process boarding one by one with 0.025s delay
        for i, passenger in enumerate(passengers_to_board):
            yield self.env.timeout(0.025 * i)
            
            # Generate passenger boarding event
            event_data = {
                "time": self.env.now,
                "event": "passenger_boarding",
                "entity_type": "station_queue",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": {
                    "passenger_id": passenger['id'],
                    "passenger_num": passenger['num'],
                    "origin": passenger['origin'],
                    "destination": passenger['destination']
                }
            }
            print(json.dumps(event_data))
            
            # Add passenger to train queue
            self.train_queue.append(passenger)

class PassengerGenerator:
    def __init__(self, env, station_queues, passenger_counter):
        self.env = env
        self.station_queues = station_queues
        self.passenger_counter = passenger_counter
        self.passenger_id_counter = 0
        
        # Start generating passengers at each station
        for station_id in STATIONS:
            env.process(self.generate_passengers_at_station(station_id))
    
    def generate_passengers_at_station(self, station_id):
        """Generate passengers at a specific station"""
        # Initial passenger at t=0.5
        yield self.env.timeout(0.5)
        
        # Generate initial passenger
        self.passenger_id_counter += 1
        passenger_id = 0  # Special case for initial passenger
        passenger_num = 0
        
        # Create passenger with random destination (different from origin)
        destination = random.choice([s for s in STATIONS if s != station_id])
        
        # Generate passenger generated event
        event_data = {
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
        print(json.dumps(event_data))
        
        # Add to station queue
        passenger = {
            "id": passenger_id,
            "num": passenger_num,
            "origin": station_id,
            "destination": destination
        }
        self.station_queues[station_id].add_passenger(passenger)
        
        # Generate regular passengers
        while True:
            # Generate interval using normal distribution
            interval = random.normalvariate(5.0, 5.0)  # Mean=5.0 min, Std=5.0 min
            interval = max(1, min(9, interval))  # Clamp to [1, 9] minutes
            interval_seconds = round(interval * 60)  # Convert to seconds
            
            yield self.env.timeout(interval_seconds)
            
            # Generate next passenger
            self.passenger_id_counter += 1
            passenger_num = self.passenger_id_counter
            
            # Create passenger with random destination (different from origin)
            destination = random.choice([s for s in STATIONS if s != station_id])
            
            # Generate passenger generated event
            event_data = {
                "time": self.env.now,
                "event": "passenger_generated",
                "entity_type": "passenger_generator",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": {
                    "passenger_id": passenger_num * 100 + station_id * 10 + destination,
                    "passenger_num": passenger_num,
                    "origin": station_id,
                    "destination": destination
                }
            }
            print(json.dumps(event_data))
            
            # Add to station queue
            passenger = {
                "id": passenger_num * 100 + station_id * 10 + destination,
                "num": passenger_num,
                "origin": station_id,
                "destination": destination
            }
            self.station_queues[station_id].add_passenger(passenger)

class StationQueue:
    def __init__(self, station_id):
        self.station_id = station_id
        self.passengers = collections.deque()
    
    def add_passenger(self, passenger):
        """Add a passenger to the queue"""
        self.passengers.append(passenger)
    
    def get_passengers(self):
        """Get all passengers in the queue (FIFO)"""
        passengers = list(self.passengers)
        self.passengers.clear()
        return passengers

def main():
    parser = argparse.ArgumentParser(description='O-Train Light Rail Simulation')
    parser.add_argument('--simulate_time', type=str, default='00:01:00:000',
                       help='Simulation duration in "HH:MM:SS:mmm"')
    
    args = parser.parse_args()
    
    # Parse simulate_time
    try:
        hours, minutes, seconds, milliseconds = map(int, args.simulate_time.split(':'))
        simulate_duration = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    except ValueError:
        print("Invalid simulate_time format. Expected HH:MM:SS:mmm", file=sys.stderr)
        sys.exit(1)
    
    print(f"Simulation duration: {simulate_duration} seconds", file=sys.stderr)
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Initialize data structures
    station_queues = {station_id: StationQueue(station_id) for station_id in STATIONS}
    train_queue = []
    passenger_counter = 0
    
    # Create components
    train = Train(env, station_queues, train_queue)
    passenger_generator = PassengerGenerator(env, station_queues, passenger_counter)
    
    # Run simulation
    env.run(until=simulate_duration)
    
    print("Simulation completed", file=sys.stderr)

if __name__ == "__main__":
    main()