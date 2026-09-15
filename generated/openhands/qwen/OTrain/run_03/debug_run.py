#!/usr/bin/env python3
"""
Debug version to test train movement
"""
import argparse
import sys
import json
import logging
import random
import time
import simpy
from collections import deque
import numpy as np

# Configure logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

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

class Passenger:
    def __init__(self, passenger_id, passenger_num, origin, destination):
        self.passenger_id = passenger_id
        self.passenger_num = passenger_num
        self.origin = origin
        self.destination = destination

class Train:
    def __init__(self, env, station_queues, train_queue, route):
        self.env = env
        self.station_queues = station_queues
        self.train_queue = train_queue
        self.route = route
        self.current_station = 1
        self.direction = 0  # 0 = Southbound, 1 = Northbound
        self.passenger_counter = 1  # Start from 1 for regular passengers
        
    def move_to_next_station(self):
        """Move train to next station in route"""
        logging.info(f"Train moving from station {self.current_station} in direction {self.direction}")
        current_index = self.route.index((self.current_station, self.direction))
        next_index = (current_index + 1) % len(self.route)
        next_station, next_direction = self.route[next_index]
        
        # Update train state
        self.current_station = next_station
        self.direction = next_direction
        
        # Schedule next arrival
        yield self.env.timeout(2.0)  # Shorter time for debugging
        
        # Trigger arrival event
        self.arrive_at_station()
        
    def arrive_at_station(self):
        """Handle train arrival at a station"""
        logging.info(f"Train arrived at station {self.current_station} in direction {self.direction}")
        
        # Log arrival event
        arrival_event = {
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
        print(json.dumps(arrival_event))
        
        # Process boarding
        self.board_passengers()
        
        # Process alighting
        self.alight_passengers()
        
        # Continue to next station
        self.env.process(self.move_to_next_station())
        
    def board_passengers(self):
        """Board passengers from station queue"""
        queue = self.station_queues[self.current_station]
        boarded_passengers = []
        
        # Board passengers one by one with 0.025s delay between each
        while queue and len(boarded_passengers) < 100:  # Max 100 passengers per station
            # Get next passenger from queue (FIFO)
            passenger = queue.popleft()
            boarded_passengers.append(passenger)
            
            # Log boarding event
            boarding_event = {
                "time": self.env.now + 0.025 * (len(boarded_passengers) - 1),
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
            print(json.dumps(boarding_event))
            
            # Add to train queue
            self.train_queue[passenger.destination].append(passenger)
            
    def alight_passengers(self):
        """Alight passengers at current station"""
        # Get passengers destined for this station
        passengers_to_alight = []
        for dest in list(self.train_queue.keys()):
            # Remove passengers destined for current station
            dest_passengers = [p for p in self.train_queue[dest] if p.destination == self.current_station]
            passengers_to_alight.extend(dest_passengers)
            
            # Remove from train queue
            self.train_queue[dest] = [p for p in self.train_queue[dest] if p.destination != self.current_station]
            
        # Alight passengers one by one with 0.025s delay between each
        for i, passenger in enumerate(passengers_to_alight):
            # Log alighting event
            alighting_event = {
                "time": self.env.now + 0.025 * i,
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
            print(json.dumps(alighting_event))

class PassengerGenerator:
    def __init__(self, env, station_queues, train_queue):
        self.env = env
        self.station_queues = station_queues
        self.train_queue = train_queue
        self.passenger_counter = 1  # Start from 1 for regular passengers
        
    def generate_passenger(self, station_id, initial=False):
        """Generate a passenger at a station"""
        # Initial passenger at t=0.5
        if initial:
            # Wait until t=0.5 for initial passenger
            yield self.env.timeout(0.5)
            passenger = Passenger(0, 0, station_id, 0)  # Special initial passenger
        else:
            # Generate passenger with random interval
            # Normal distribution with mean=5.0 min, std=5.0 min
            interval_minutes = np.random.normal(5.0, 5.0)
            # Clamp to [1, 9] minutes
            interval_minutes = max(1.0, min(9.0, interval_minutes))
            # Convert to seconds and round
            interval_seconds = round(interval_minutes * 60)
            
            # Generate destination (different from origin)
            destinations = [s for s in STATIONS.keys() if s != station_id]
            destination = random.choice(destinations)
            
            # Create passenger ID
            passenger_id = self.passenger_counter * 100 + station_id * 10 + destination
            passenger = Passenger(passenger_id, self.passenger_counter, station_id, destination)
            self.passenger_counter += 1
            
        # Log passenger generation event
        gen_event = {
            "time": self.env.now,
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
        print(json.dumps(gen_event))
        
        # Add to station queue
        self.station_queues[station_id].append(passenger)
        
        # Schedule next passenger generation
        if not initial:
            yield self.env.timeout(interval_seconds)
            self.env.process(self.generate_passenger(station_id))
    
def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='O-Train Light Rail Simulation')
    parser.add_argument('--simulate_time', type=str, default='00:00:10:000',
                        help='Simulation duration in HH:MM:SS:mmm format')
    args = parser.parse_args()
    
    # Parse simulate_time
    try:
        hours, minutes, seconds, milliseconds = map(int, args.simulate_time.split(':'))
        simulate_duration = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
    except ValueError:
        print("Invalid simulate_time format. Using default 10 seconds.", file=sys.stderr)
        simulate_duration = 10.0
    
    # Set random seed using system time
    random.seed(time.time_ns())
    np.random.seed(time.time_ns() % (2**32 - 1))
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Initialize station queues (FIFO queues for each station)
    station_queues = {i: deque() for i in range(1, 6)}
    
    # Initialize train queue (passengers grouped by destination)
    train_queue = {i: deque() for i in range(1, 6)}
    
    # Create train
    train = Train(env, station_queues, train_queue, ROUTE)
    
    # Create passenger generators for each station
    generators = []
    for station_id in range(1, 6):
        generator = PassengerGenerator(env, station_queues, train_queue)
        generators.append(generator)
        
        # Schedule initial passenger at t=0.5
        env.process(generator.generate_passenger(station_id, initial=True))
        
        # Schedule regular passenger generation
        env.process(generator.generate_passenger(station_id))
    
    # Start train at Bayview (station 1, direction 0) at time 0.0
    env.process(train.move_to_next_station())
    
    # Run simulation
    env.run(until=simulate_duration)
    
    # Print final status
    logging.info(f"Simulation completed at time {simulate_duration:.3f}")

if __name__ == "__main__":
    main()