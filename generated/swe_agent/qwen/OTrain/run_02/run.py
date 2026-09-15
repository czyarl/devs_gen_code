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

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)

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
        self.direction = 0
        self.passenger_count = 0
        
    def run(self):
        # Initial arrival at Bayview (Station 1, Direction 0)
        yield self.env.timeout(0.0)
        self.arrive_at_station()
        
        # Continue the route
        while True:
            # Move to next station
            current_index = TRAIN_ROUTE.index((self.current_station, self.direction))
            next_index = (current_index + 1) % len(TRAIN_ROUTE)
            next_station, next_direction = TRAIN_ROUTE[next_index]
            
            # Travel time between stations is 225 seconds
            yield self.env.timeout(225.0)
            
            # Update train state
            self.current_station = next_station
            self.direction = next_direction
            
            # Arrive at next station
            self.arrive_at_station()
    
    def arrive_at_station(self):
        # Generate train arrival event
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
        sys.stdout.flush()
        
        # Process boarding
        self.board_passengers()
        
        # Process alighting
        self.alight_passengers()
    
    def board_passengers(self):
        # Get passengers waiting at this station
        passengers = self.station_queues[self.current_station].get_passengers()
        
        # Board passengers one by one with 0.025s delay
        for i, passenger in enumerate(passengers):
            # Delay: first passenger boards 0.025s after train arrival
            # Subsequent passengers board 0.025s after previous one
            delay = 0.025 * i
            yield self.env.timeout(delay)
            
            # Generate passenger boarding event
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
            sys.stdout.flush()
            
            # Move passenger to train queue
            self.train_queue.add_passenger(passenger)
    
    def alight_passengers(self):
        # Get passengers destined for this station
        passengers = self.train_queue.get_passengers_for_station(self.current_station)
        
        # Alight passengers one by one with 0.025s delay
        for i, passenger in enumerate(passengers):
            # Delay: first passenger alights 0.025s after train arrival
            # Subsequent passengers alight 0.025s after previous one
            delay = 0.025 * i
            yield self.env.timeout(delay)
            
            # Generate passenger exiting event
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
            sys.stdout.flush()
            
            # Remove passenger from train queue
            self.train_queue.remove_passenger(passenger)

class StationQueue:
    def __init__(self, station_id, station_name):
        self.station_id = station_id
        self.station_name = station_name
        self.passengers = []
    
    def add_passenger(self, passenger):
        # Only add passengers whose origin matches this station
        if passenger.origin == self.station_id:
            self.passengers.append(passenger)
    
    def get_passengers(self):
        # Return passengers in FIFO order
        return self.passengers.copy()
    
    def remove_passenger(self, passenger):
        # Remove a specific passenger from the queue
        if passenger in self.passengers:
            self.passengers.remove(passenger)

class TrainQueue:
    def __init__(self):
        self.passengers_by_destination = defaultdict(list)
    
    def add_passenger(self, passenger):
        # Add passenger to the queue for their destination
        self.passengers_by_destination[passenger.destination].append(passenger)
    
    def get_passengers_for_station(self, station_id):
        # Get passengers destined for this station
        return self.passengers_by_destination[station_id].copy()
    
    def remove_passenger(self, passenger):
        # Remove a passenger from the queue for their destination
        if passenger.destination in self.passengers_by_destination:
            if passenger in self.passengers_by_destination[passenger.destination]:
                self.passengers_by_destination[passenger.destination].remove(passenger)

class PassengerGenerator:
    def __init__(self, env, station_queues):
        self.env = env
        self.station_queues = station_queues
        self.passenger_num = 1  # Start from 1 for normal passengers
        
    def run(self):
        # Generate initial passengers at t=0.5 seconds
        yield self.env.timeout(0.5)
        for station_id in STATIONS:
            # For initial passengers, we need to generate a valid destination
            # (different from origin)
            destination_station = random.choice([i for i in range(1, 6) if i != station_id])
            self.generate_passenger(station_id, destination_station, 0)  # Initial passenger with ID=0
            
        # Continue generating passengers
        while True:
            # Generate interval using normal distribution (mean=5.0 min, std=5.0 min)
            interval_minutes = random.normalvariate(5.0, 5.0)
            # Clamp to range [1, 9] minutes
            interval_minutes = max(1.0, min(9.0, interval_minutes))
            # Convert to seconds and round to nearest integer
            interval_seconds = round(interval_minutes * 60)
            
            # Wait for the interval
            yield self.env.timeout(interval_seconds)
            
            # Generate a new passenger at a random station
            origin_station = random.randint(1, 5)
            # Choose destination (different from origin)
            destination_station = random.choice([i for i in range(1, 6) if i != origin_station])
            
            # Generate the passenger with the current passenger number
            self.generate_passenger(origin_station, destination_station, self.passenger_num)
            # Increment the passenger number for the next passenger
            self.passenger_num += 1
    
    def generate_passenger(self, origin_station, destination_station, passenger_num):
        # Special case for initial passenger (ID=0)
        if passenger_num == 0:
            passenger_id = 0
        else:
            # Formula: passenger_id = passenger_num * 100 + origin * 10 + destination
            passenger_id = passenger_num * 100 + origin_station * 10 + destination_station
            
        # Create passenger
        passenger = Passenger(passenger_id, passenger_num, origin_station, destination_station)
        
        # Generate passenger generated event
        event_data = {
            "time": self.env.now,
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": origin_station,
            "station": STATIONS[origin_station],
            "payload": {
                "passenger_id": passenger_id,
                "passenger_num": passenger_num,
                "origin": origin_station,
                "destination": destination_station
            }
        }
        print(json.dumps(event_data))
        sys.stdout.flush()
        
        # Add passenger to the station queue
        self.station_queues[origin_station].add_passenger(passenger)

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='O-Train Light Rail Simulation')
    parser.add_argument('--simulate_time', type=str, default='00:01:00:000', 
                       help='Simulation duration in "HH:MM:SS:mmm"')
    
    args = parser.parse_args()
    
    # Parse simulate_time
    try:
        hours, minutes, seconds, milliseconds = map(int, args.simulate_time.split(':'))
        simulate_duration = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
    except ValueError:
        logging.error("Invalid simulate_time format. Expected HH:MM:SS:mmm")
        sys.exit(1)
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create station queues
    station_queues = {i: StationQueue(i, STATIONS[i]) for i in range(1, 6)}
    
    # Create train queue
    train_queue = TrainQueue()
    
    # Create train
    train = Train(env, station_queues, train_queue)
    
    # Create passenger generator
    passenger_generator = PassengerGenerator(env, station_queues)
    
    # Start simulation processes
    env.process(train.run())
    env.process(passenger_generator.run())
    
    # Run simulation for specified duration
    try:
        env.run(until=simulate_duration)
    except Exception as e:
        logging.error(f"Simulation error: {e}")
        sys.exit(1)
    
    # Print final state
    final_state = {
        "time": env.now,
        "event": "simulation_end",
        "entity_type": "simulation",
        "payload": {
            "duration": simulate_duration
        }
    }
    print(json.dumps(final_state))
    sys.stdout.flush()

if __name__ == "__main__":
    main()