#!/usr/bin/env python3
"""
O-Train Light Rail Simulation
Simulates a single train moving between 5 stations with passenger generation,
boarding, and alighting processes.
"""

import argparse
import sys
import json
import logging
import random
import time
import math
import simpy
from collections import deque

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

def generate_passenger_id(passenger_num, origin, destination):
    """Generate passenger ID using the specified formula."""
    if passenger_num == 0 and origin == 0 and destination == 0:
        return 0  # Special case for initial passenger
    return passenger_num * 100 + origin * 10 + destination

class Passenger:
    """Represents a passenger in the simulation."""
    def __init__(self, passenger_id, passenger_num, origin, destination):
        self.passenger_id = passenger_id
        self.passenger_num = passenger_num
        self.origin = origin
        self.destination = destination

class Train:
    """Manages train operations and passenger on-board."""
    def __init__(self, env, station_queues, train_queue):
        self.env = env
        self.station_queues = station_queues
        self.train_queue = train_queue
        self.current_station = 1
        self.direction = 0  # 0 = Southbound, 1 = Northbound
        self.passengers = []  # List of passengers currently on train
        
    def move_to_next_station(self):
        """Move train to next station in the route."""
        current_index = ROUTE.index((self.current_station, self.direction))
        next_index = (current_index + 1) % len(ROUTE)
        next_station, next_direction = ROUTE[next_index]
        
        # Update train state
        self.current_station = next_station
        self.direction = next_direction
        
        return next_station, next_direction
    
    def process_arrival(self, station_id):
        """Process train arrival at a station."""
        # Generate train arrival event
        event = {
            "time": self.env.now,
            "event": "train_arrival",
            "entity_type": "train",
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": {
                "station": station_id,
                "direction": self.direction
            }
        }
        print(json.dumps(event))
        
        # Process alighting passengers
        self.process_alighting(station_id)
        
        # Process boarding passengers
        self.process_boarding(station_id)
        
    def process_alighting(self, station_id):
        """Process passengers alighting at current station."""
        # Find passengers destined for this station
        alighting_passengers = [p for p in self.passengers if p.destination == station_id]
        
        # Process each alighting passenger
        for i, passenger in enumerate(alighting_passengers):
            # Delay: first passenger 0.025s after arrival, then 0.025s between each
            delay = 0.025 * i
            yield self.env.timeout(delay)
            
            # Remove passenger from train
            self.passengers.remove(passenger)
            
            # Generate passenger exiting event
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
            print(json.dumps(event))
    
    def process_boarding(self, station_id):
        """Process passengers boarding at current station."""
        # Get queue for this station
        queue = self.station_queues[station_id]
        
        # Process each passenger in queue
        boarding_passengers = []
        while queue and len(boarding_passengers) < 10:  # Max 10 passengers per station
            passenger = queue.popleft()
            # Check if passenger's origin matches current station
            if passenger.origin == station_id:
                boarding_passengers.append(passenger)
            else:
                # If not, put back in queue (shouldn't happen in normal operation)
                queue.append(passenger)
        
        # Process each boarding passenger
        for i, passenger in enumerate(boarding_passengers):
            # Delay: first passenger 0.025s after arrival, then 0.025s between each
            delay = 0.025 * i
            yield self.env.timeout(delay)
            
            # Add passenger to train
            self.passengers.append(passenger)
            
            # Generate passenger boarding event
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
            print(json.dumps(event))

class PassengerGenerator:
    """Generates passengers at each station."""
    def __init__(self, env, station_queues):
        self.env = env
        self.station_queues = station_queues
        self.passenger_counter = 0
        
    def generate_initial_passengers(self):
        """Generate initial passengers at all stations at t=0.5."""
        for station_id in STATIONS:
            self.passenger_counter += 1
            passenger_id = generate_passenger_id(0, station_id, 0)  # Special case
            passenger = Passenger(passenger_id, 0, station_id, 0)
            
            # Add to station queue
            self.station_queues[station_id].append(passenger)
            
            # Generate passenger generated event
            event = {
                "time": 0.5,
                "event": "passenger_generated",
                "entity_type": "passenger_generator",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": {
                    "passenger_id": passenger_id,
                    "passenger_num": 0,
                    "origin": station_id,
                    "destination": 0
                }
            }
            print(json.dumps(event))
    
    def generate_passenger(self, station_id):
        """Generate a new passenger at a station."""
        # Generate destination (different from origin)
        destinations = [i for i in range(1, 6) if i != station_id]
        destination = random.choice(destinations)
        
        # Generate passenger ID
        self.passenger_counter += 1
        passenger_id = generate_passenger_id(self.passenger_counter, station_id, destination)
        passenger = Passenger(passenger_id, self.passenger_counter, station_id, destination)
        
        # Add to station queue
        self.station_queues[station_id].append(passenger)
        
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
        print(json.dumps(event))
        
        # Schedule next passenger generation
        # Normal distribution with mean=5 min, std=5 min, clamped to [1,9] minutes
        interval_minutes = random.normalvariate(5.0, 5.0)
        interval_minutes = max(1, min(9, interval_minutes))  # Clamp to [1,9]
        interval_seconds = round(interval_minutes * 60)
        
        yield self.env.timeout(interval_seconds)
        self.generate_passenger(station_id)

def run_simulation(simulate_time):
    """Run the O-Train simulation."""
    # Create simulation environment
    env = simpy.Environment()
    
    # Initialize station queues
    station_queues = {i: deque() for i in range(1, 6)}
    
    # Initialize train queue (empty initially)
    train_queue = []
    
    # Create train
    train = Train(env, station_queues, train_queue)
    
    # Create passenger generator
    generator = PassengerGenerator(env, station_queues)
    
    # Generate initial passengers
    generator.generate_initial_passengers()
    
    # Schedule initial train arrival
    env.process(train_arrival_process(env, train))
    
    # Schedule passenger generation for each station
    for station_id in STATIONS:
        env.process(generator.generate_passenger(station_id))
    
    # Run simulation
    env.run(until=simulate_time)
    
def train_arrival_process(env, train):
    """Process train arrivals at stations."""
    # Initial arrival at Bayview (station 1, direction 0)
    train.current_station = 1
    train.direction = 0
    train.process_arrival(1)
    
    # Continue with regular schedule
    while True:
        # Move to next station
        next_station, next_direction = train.move_to_next_station()
        
        # Wait for travel time
        yield env.timeout(TRAVEL_TIME)
        
        # Process arrival
        train.process_arrival(next_station)

def main():
    """Main function to parse arguments and run simulation."""
    parser = argparse.ArgumentParser(description='O-Train Light Rail Simulation')
    parser.add_argument('--simulate_time', 
                       default='00:01:00:000',
                       help='Simulation duration in HH:MM:SS:mmm (default: 00:01:00:000)')
    
    args = parser.parse_args()
    
    # Parse simulate_time
    try:
        hours, minutes, seconds, milliseconds = map(int, args.simulate_time.split(':'))
        simulate_time = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
    except ValueError:
        print("Error: Invalid simulate_time format. Use HH:MM:SS:mmm", file=sys.stderr)
        sys.exit(1)
    
    # Run simulation
    run_simulation(simulate_time)

if __name__ == "__main__":
    main()