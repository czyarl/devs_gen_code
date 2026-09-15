#!/usr/bin/env python3
"""
O-Train Light Rail Simulation
Simulates a single train moving between 5 stations with passenger generation,
boarding, and alighting processes.
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

# Route sequence (station_id, direction)
ROUTE = [
    (1, 0), (2, 0), (3, 0), (4, 0), (5, 1), 
    (4, 1), (3, 1), (2, 1), (1, 0)
]

# Simulation parameters
TRAIN_TRAVEL_TIME = 225  # seconds between consecutive stations
INITIAL_PASSENGER_TIME = 0.5  # seconds
PASSENGER_GENERATION_MEAN = 5 * 60  # 5 minutes in seconds
PASSENGER_GENERATION_STD = 5 * 60  # 5 minutes in seconds
BOARDING_ALIGHTING_DELAY = 0.025  # seconds between passengers

class PassengerGenerator:
    """Generates passengers at each station"""
    
    def __init__(self, env, station_id, station_name, passenger_queue):
        self.env = env
        self.station_id = station_id
        self.station_name = station_name
        self.passenger_queue = passenger_queue
        self.passenger_num = 0
        
    def generate_passengers(self):
        """Generate passengers at this station"""
        # Generate initial passenger at t=0.5
        yield self.env.timeout(INITIAL_PASSENGER_TIME)
        self._generate_single_passenger(0)
        
        # Generate regular passengers
        while True:
            # Generate interval using normal distribution
            interval = random.normalvariate(PASSENGER_GENERATION_MEAN, PASSENGER_GENERATION_STD)
            # Clamp to [1, 9] minutes
            interval = max(60, min(540, interval))
            interval = round(interval)  # Round to nearest second
            
            yield self.env.timeout(interval)
            self._generate_single_passenger(self.passenger_num)
            self.passenger_num += 1
            
    def _generate_single_passenger(self, passenger_num):
        """Generate a single passenger"""
        # For initial passenger, ID is 0
        if passenger_num == 0:
            passenger_id = 0
        else:
            # Select random destination (different from origin)
            destinations = [i for i in range(1, 6) if i != self.station_id]
            destination = random.choice(destinations)
            passenger_id = passenger_num * 100 + self.station_id * 10 + destination
            
        # Create passenger event
        event = {
            "time": self.env.now,
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": self.station_id,
            "station": self.station_name,
            "payload": {
                "passenger_id": passenger_id,
                "passenger_num": passenger_num,
                "origin": self.station_id,
                "destination": destination if passenger_num != 0 else None
            }
        }
        
        # Print to stdout (JSONL format)
        print(json.dumps(event))
        sys.stdout.flush()
        
        # Add to queue
        if passenger_num != 0:
            self.passenger_queue[self.station_id].append({
                "passenger_id": passenger_id,
                "passenger_num": passenger_num,
                "origin": self.station_id,
                "destination": destination
            })

class Train:
    """Controls the movement of the single train"""
    
    def __init__(self, env, passenger_queues):
        self.env = env
        self.passenger_queues = passenger_queues
        self.current_station = 1
        self.current_direction = 0  # 0 = Southbound, 1 = Northbound
        self.passengers = []  # List of passengers currently on train
        
    def move_train(self):
        """Move the train along the route"""
        # Start at Bayview (station 1, direction 0)
        yield self.env.timeout(0)
        
        # Create initial train arrival event
        self._create_train_arrival_event()
        
        # Continue moving along the route
        while True:
            # Move to next station
            current_index = ROUTE.index((self.current_station, self.current_direction))
            next_index = (current_index + 1) % len(ROUTE)
            next_station, next_direction = ROUTE[next_index]
            
            # Wait for travel time
            yield self.env.timeout(TRAIN_TRAVEL_TIME)
            
            # Update train position
            self.current_station = next_station
            self.current_direction = next_direction
            
            # Create train arrival event
            self._create_train_arrival_event()
            
    def _create_train_arrival_event(self):
        """Create a train arrival event"""
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
        
        # Print to stdout (JSONL format)
        print(json.dumps(event))
        sys.stdout.flush()
        
        # Process boarding and alighting at this station
        self.env.process(self._process_station_events(self.current_station, self.current_direction))
        
    def _process_station_events(self, station_id, direction):
        """Process boarding and alighting at a station"""
        # First, alight passengers destined for this station
        yield self.env.process(self._alight_passengers(station_id))
        
        # Then, board passengers from the station queue
        yield self.env.process(self._board_passengers(station_id))
        
    def _alight_passengers(self, station_id):
        """Remove passengers destined for this station"""
        # Alight passengers one by one with delay
        passengers_to_remove = []
        for i, passenger in enumerate(self.passengers):
            if passenger["destination"] == station_id:
                # Wait for alighting delay
                if i == 0:
                    yield self.env.timeout(0)
                else:
                    yield self.env.timeout(BOARDING_ALIGHTING_DELAY)
                
                # Create exiting event
                event = {
                    "time": self.env.now,
                    "event": "passenger_exiting",
                    "entity_type": "train_queue",
                    "station_id": station_id,
                    "station": STATIONS[station_id],
                    "payload": {
                        "passenger_id": passenger["passenger_id"],
                        "passenger_num": passenger["passenger_num"],
                        "origin": passenger["origin"],
                        "destination": passenger["destination"]
                    }
                }
                
                # Print to stdout (JSONL format)
                print(json.dumps(event))
                sys.stdout.flush()
                
                # Mark for removal
                passengers_to_remove.append(passenger)
                
        # Remove passengers from train
        for passenger in passengers_to_remove:
            self.passengers.remove(passenger)
            
    def _board_passengers(self, station_id):
        """Board passengers from the station queue"""
        # Board passengers one by one with delay
        queue = self.passenger_queues[station_id]
        passengers_to_board = []
        
        # Collect passengers to board (FIFO) - only those from this station
        passengers_to_remove = []
        for passenger in queue:
            if passenger["origin"] == station_id:
                passengers_to_board.append(passenger)
            else:
                # Keep passengers that don't belong to this station for later
                passengers_to_remove.append(passenger)
        
        # Remove passengers that don't belong to this station
        for passenger in passengers_to_remove:
            queue.remove(passenger)
                
        # Board passengers one by one
        for i, passenger in enumerate(passengers_to_board):
            # Wait for boarding delay
            if i == 0:
                yield self.env.timeout(0)
            else:
                yield self.env.timeout(BOARDING_ALIGHTING_DELAY)
            
            # Create boarding event
            event = {
                "time": self.env.now,
                "event": "passenger_boarding",
                "entity_type": "station_queue",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": {
                    "passenger_id": passenger["passenger_id"],
                    "passenger_num": passenger["passenger_num"],
                    "origin": passenger["origin"],
                    "destination": passenger["destination"]
                }
            }
            
            # Print to stdout (JSONL format)
            print(json.dumps(event))
            sys.stdout.flush()
            
            # Add to train
            self.passengers.append(passenger)
            
            # Remove from queue
            queue.remove(passenger)

def main():
    parser = argparse.ArgumentParser(description='O-Train Light Rail Simulation')
    parser.add_argument('--simulate_time', type=str, default='00:01:00:000',
                        help='Simulation duration in HH:MM:SS:mmm (default: 00:01:00:000)')
    
    args = parser.parse_args()
    
    # Parse simulation time
    try:
        hours, minutes, seconds, milliseconds = map(int, args.simulate_time.split(':'))
        simulate_time = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
    except ValueError:
        print("Error: Invalid simulate_time format. Use HH:MM:SS:mmm", file=sys.stderr)
        sys.exit(1)
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create passenger queues for each station
    passenger_queues = defaultdict(list)
    
    # Create passenger generators
    generators = {}
    for station_id, station_name in STATIONS.items():
        generators[station_id] = PassengerGenerator(env, station_id, station_name, passenger_queues)
        env.process(generators[station_id].generate_passengers())
    
    # Create train
    train = Train(env, passenger_queues)
    
    # Process train movement
    env.process(train.move_train())
    
    # Run simulation
    env.run(until=simulate_time)
    
    # Print final status
    print(json.dumps({
        "time": env.now,
        "event": "simulation_end",
        "entity_type": "system",
        "station_id": None,
        "station": None,
        "payload": {
            "duration": simulate_time
        }
    }))

if __name__ == "__main__":
    main()