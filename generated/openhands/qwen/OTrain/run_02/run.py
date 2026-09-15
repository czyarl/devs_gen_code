#!/usr/bin/env python3
"""
O-Train Light Rail Simulation
Simulates a single train moving between 5 stations with passenger generation, boarding, and alighting.
"""
import argparse
import sys
import json
import logging
import random
import time
import simpy
from collections import defaultdict, deque

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

# Passenger generation parameters
PASS_GEN_MEAN = 5.0 * 60  # 5 minutes in seconds
PASS_GEN_STD = 5.0 * 60   # 5 minutes in seconds
PASS_GEN_MIN = 1 * 60     # 1 minute in seconds
PASS_GEN_MAX = 9 * 60     # 9 minutes in seconds

class Train:
    def __init__(self, env, station_queues, train_queue):
        self.env = env
        self.station_queues = station_queues
        self.train_queue = train_queue
        self.current_station = 1
        self.direction = 0
        self.passenger_count = 0
        
    def move_to_next_station(self):
        """Move train to next station in the route"""
        # Find current position in route
        current_idx = None
        for i, (station, direction) in enumerate(ROUTE):
            if station == self.current_station and direction == self.direction:
                current_idx = i
                break
        
        # Move to next station in route
        if current_idx is not None:
            next_idx = (current_idx + 1) % len(ROUTE)
            next_station, next_direction = ROUTE[next_idx]
        else:
            # Default to starting position if not found
            next_station, next_direction = ROUTE[0]
        
        # Wait for travel time
        yield self.env.timeout(TRAVEL_TIME)
        
        # Update train state
        self.current_station = next_station
        self.direction = next_direction
        
        # Generate train arrival event
        event_data = {
            "time": self.env.now,
            "event": "train_arrival",
            "entity_type": "train",
            "station_id": next_station,
            "station": STATIONS[next_station],
            "payload": {
                "station": next_station,
                "direction": next_direction
            }
        }
        print(json.dumps(event_data), file=sys.stderr)
        print(json.dumps(event_data))
        
        # Process boarding and alighting
        yield self.env.process(self.board_passengers())
        yield self.env.process(self.alight_passengers())
        
    def board_passengers(self):
        """Board passengers from the station queue"""
        queue = self.station_queues[self.current_station]
        passengers_to_board = []
        
        # Collect passengers who want to go in the same direction
        while queue:
            passenger = queue.popleft()
            # Check if passenger wants to go in the same direction
            if self.direction == 0:  # Southbound
                if passenger['destination'] > self.current_station:
                    passengers_to_board.append(passenger)
                else:
                    # If not going in the right direction, put back in queue
                    queue.appendleft(passenger)
            else:  # Northbound
                if passenger['destination'] < self.current_station:
                    passengers_to_board.append(passenger)
                else:
                    # If not going in the right direction, put back in queue
                    queue.appendleft(passenger)
        
        # Board passengers one by one with 0.025s delay
        for i, passenger in enumerate(passengers_to_board):
            # Delay for boarding
            if i == 0:
                yield self.env.timeout(0.025)
            else:
                yield self.env.timeout(0.025)
            
            # Generate boarding event
            event_data = {
                "time": self.env.now,
                "event": "passenger_boarding",
                "entity_type": "station_queue",
                "station_id": self.current_station,
                "station": STATIONS[self.current_station],
                "payload": passenger
            }
            print(json.dumps(event_data), file=sys.stderr)
            print(json.dumps(event_data))
            
            # Add to train queue
            self.train_queue[passenger['destination']].append(passenger)
            self.passenger_count += 1
    
    def alight_passengers(self):
        """Allow passengers to alight at current station"""
        # Get passengers destined for this station
        passengers_to_alight = self.train_queue[self.current_station]
        
        # Alight passengers one by one with 0.025s delay
        for i, passenger in enumerate(passengers_to_alight):
            # Delay for alighting
            if i == 0:
                yield self.env.timeout(0.025)
            else:
                yield self.env.timeout(0.025)
            
            # Generate exiting event
            event_data = {
                "time": self.env.now,
                "event": "passenger_exiting",
                "entity_type": "train_queue",
                "station_id": self.current_station,
                "station": STATIONS[self.current_station],
                "payload": passenger
            }
            print(json.dumps(event_data), file=sys.stderr)
            print(json.dumps(event_data))
            
            # Remove from train queue
            self.train_queue[self.current_station].remove(passenger)
            self.passenger_count -= 1

class PassengerGenerator:
    def __init__(self, env, station_queues):
        self.env = env
        self.station_queues = station_queues
        self.passenger_num = 0
        
    def generate_passenger(self, station_id):
        """Generate a passenger at a station"""
        # Initial passenger at t=0.5
        if self.env.now == 0.5:
            passenger_id = 0
            # Generate destination (different from origin)
            destinations = [s for s in STATIONS.keys() if s != station_id]
            destination = random.choice(destinations)
        else:
            # Regular passenger generation
            self.passenger_num += 1
            # Generate interval with normal distribution
            interval = random.normalvariate(PASS_GEN_MEAN, PASS_GEN_STD)
            # Clamp to range [1, 9] minutes
            interval = max(PASS_GEN_MIN, min(PASS_GEN_MAX, interval))
            interval = round(interval)  # Round to nearest second
            
            # Wait for interval
            yield self.env.timeout(interval)
            
            # Generate passenger ID
            passenger_id = self.passenger_num * 100 + station_id * 10
            
            # Generate destination (different from origin)
            destinations = [s for s in STATIONS.keys() if s != station_id]
            destination = random.choice(destinations)
            
            # Update passenger ID with destination
            passenger_id += destination
            
        # Create passenger data
        passenger = {
            "passenger_id": passenger_id,
            "passenger_num": self.passenger_num if passenger_id != 0 else 0,
            "origin": station_id,
            "destination": destination
        }
        
        # Generate passenger generated event
        event_data = {
            "time": self.env.now,
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": passenger
        }
        print(json.dumps(event_data), file=sys.stderr)
        print(json.dumps(event_data))
        
        # Add to station queue
        self.station_queues[station_id].append(passenger)

def main():
    parser = argparse.ArgumentParser(description='O-Train Light Rail Simulation')
    parser.add_argument('--simulate_time', type=str, default='00:01:00:000',
                        help='Simulation duration in HH:MM:SS:mmm format')
    
    args = parser.parse_args()
    
    # Parse simulation time
    hours, minutes, seconds, milliseconds = map(int, args.simulate_time.split(':'))
    total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Initialize station queues (FIFO queues for each station)
    station_queues = defaultdict(deque)
    
    # Initialize train queue (grouped by destination)
    train_queue = defaultdict(deque)
    
    # Create train
    train = Train(env, station_queues, train_queue)
    
    # Create passenger generators
    passenger_generators = []
    for station_id in STATIONS.keys():
        pg = PassengerGenerator(env, station_queues)
        passenger_generators.append(pg)
        
        # Generate initial passenger at t=0.5
        env.process(pg.generate_passenger(station_id))
    
    # Start train at Bayview (station 1, direction 0) after initial passengers are generated
    # Schedule the first train movement after a small delay to allow initial events to be processed
    env.process(train.move_to_next_station())
    
    # Run simulation
    env.run(until=total_seconds)
    
    # Print final state
    final_state = {
        "time": total_seconds,
        "event": "simulation_end",
        "entity_type": "system",
        "station_id": 0,
        "station": "System",
        "payload": {
            "total_passengers_generated": sum(len(q) for q in station_queues.values()) + sum(len(q) for q in train_queue.values()),
            "passengers_on_train": sum(len(q) for q in train_queue.values()),
            "station_queues": {station: len(queue) for station, queue in station_queues.items()}
        }
    }
    print(json.dumps(final_state))

if __name__ == "__main__":
    main()