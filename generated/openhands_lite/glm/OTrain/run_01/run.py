#!/usr/bin/env python3
"""
O-Train Light Rail Simulation
Discrete event simulation of a single train shuttling passengers between 5 stations.
"""

import argparse
import sys
import json
import logging
import random
import time
import simpy
from collections import deque

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# Station configuration
STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro"
}

# Route configuration
# Southbound (direction=0): Bayview→Carling→Carleton→Confed→Greenboro
# Northbound (direction=1): Greenboro→Confed→Carleton→Carling→Bayview
SOUTHBOUND_ROUTE = [1, 2, 3, 4, 5]
NORTHBOUND_ROUTE = [5, 4, 3, 2, 1]

# Travel time between consecutive stations (seconds)
TRAVEL_TIME = 225

# Boarding/alighting delay per passenger (seconds)
PASSENGER_DELAY = 0.025


class PassengerGenerator:
    """Generates passengers at a station."""
    
    def __init__(self, env, station_id, station_queue):
        self.env = env
        self.station_id = station_id
        self.station_queue = station_queue
        self.passenger_num = 0
    
    def log_event(self, event_data):
        """Log an event to stdout as JSON."""
        print(json.dumps(event_data))
    
    def generate_initial_passenger(self):
        """Generate the initial passenger at t=0.5 seconds."""
        yield self.env.timeout(0.5)
        self.passenger_num = 0
        self.generate_passenger(0)
    
    def generate_passenger(self, passenger_num):
        """Generate a passenger and log the event."""
        # Select destination (uniform from other stations)
        possible_destinations = [s for s in STATIONS.keys() if s != self.station_id]
        destination = random.choice(possible_destinations)
        
        # Calculate passenger ID
        if passenger_num == 0:
            passenger_id = 0
        else:
            passenger_id = passenger_num * 100 + self.station_id * 10 + destination
        
        # Log passenger generation event
        self.log_event({
            'time': self.env.now,
            'event': 'passenger_generated',
            'entity_type': 'passenger_generator',
            'station_id': self.station_id,
            'station': STATIONS[self.station_id],
            'payload': {
                'passenger_id': passenger_id,
                'passenger_num': passenger_num,
                'origin': self.station_id,
                'destination': destination
            }
        })
        
        # Add to station queue
        self.station_queue.add_passenger(passenger_id, passenger_num, self.station_id, destination)
    
    def run(self):
        """Main passenger generation process."""
        # Generate initial passenger at t=0.5
        yield self.env.process(self.generate_initial_passenger())
        
        # Generate subsequent passengers
        while True:
            # Calculate next interval using normal distribution
            interval_minutes = random.normalvariate(5.0, 5.0)
            # Clamp to [1, 9] minutes
            interval_minutes = max(1.0, min(9.0, interval_minutes))
            # Convert to seconds and round to nearest integer
            interval_seconds = int(round(interval_minutes * 60))
            
            yield self.env.timeout(interval_seconds)
            
            self.passenger_num += 1
            self.generate_passenger(self.passenger_num)


class StationQueue:
    """Manages passengers waiting at a station."""
    
    def __init__(self, env, station_id):
        self.env = env
        self.station_id = station_id
        self.queue = deque()
    
    def add_passenger(self, passenger_id, passenger_num, origin, destination):
        """Add a passenger to the queue."""
        self.queue.append({
            'passenger_id': passenger_id,
            'passenger_num': passenger_num,
            'origin': origin,
            'destination': destination
        })
    
    def log_event(self, event_data):
        """Log an event to stdout as JSON."""
        print(json.dumps(event_data))
    
    def process_boarding(self, train):
        """Process boarding of passengers at this station."""
        # Board passengers one by one with delay
        while self.queue:
            passenger = self.queue.popleft()
            
            # Wait for boarding delay
            yield self.env.timeout(PASSENGER_DELAY)
            
            # Log boarding event
            self.log_event({
                'time': self.env.now,
                'event': 'passenger_boarding',
                'entity_type': 'station_queue',
                'station_id': self.station_id,
                'station': STATIONS[self.station_id],
                'payload': {
                    'passenger_id': passenger['passenger_id'],
                    'passenger_num': passenger['passenger_num'],
                    'origin': passenger['origin'],
                    'destination': passenger['destination']
                }
            })
            
            # Add passenger to train
            train.add_passenger(passenger)


class Train:
    """Represents the train moving between stations."""
    
    def __init__(self, env, station_queues):
        self.env = env
        self.station_queues = station_queues
        self.passengers = []  # List of passengers on train
        self.current_route = SOUTHBOUND_ROUTE
        self.current_index = 0
        self.direction = 0  # 0=Southbound, 1=Northbound
    
    def add_passenger(self, passenger):
        """Add a passenger to the train."""
        self.passengers.append(passenger)
    
    def log_event(self, event_data):
        """Log an event to stdout as JSON."""
        print(json.dumps(event_data))
    
    def process_alighting(self, station_id):
        """Process passengers alighting at this station."""
        # Find passengers destined for this station
        alighting_passengers = [p for p in self.passengers if p['destination'] == station_id]
        
        # Remove them from train
        self.passengers = [p for p in self.passengers if p['destination'] != station_id]
        
        # Process alighting one by one with delay
        for passenger in alighting_passengers:
            yield self.env.timeout(PASSENGER_DELAY)
            
            # Log exiting event
            self.log_event({
                'time': self.env.now,
                'event': 'passenger_exiting',
                'entity_type': 'train_queue',
                'station_id': station_id,
                'station': STATIONS[station_id],
                'payload': {
                    'passenger_id': passenger['passenger_id'],
                    'passenger_num': passenger['passenger_num'],
                    'origin': passenger['origin'],
                    'destination': passenger['destination']
                }
            })
    
    def run(self):
        """Main train operation process."""
        while True:
            # Get current station
            station_id = self.current_route[self.current_index]
            
            # Log train arrival event
            self.log_event({
                'time': self.env.now,
                'event': 'train_arrival',
                'entity_type': 'train',
                'station_id': station_id,
                'station': STATIONS[station_id],
                'payload': {
                    'station': station_id,
                    'direction': self.direction
                }
            })
            
            # Process alighting first
            yield self.env.process(self.process_alighting(station_id))
            
            # Process boarding
            station_queue = self.station_queues[station_id]
            yield self.env.process(station_queue.process_boarding(self))
            
            # Move to next station
            self.current_index += 1
            
            # Check if we need to switch direction
            if self.current_index >= len(self.current_route):
                # Switch direction
                if self.direction == 0:
                    self.direction = 1
                    self.current_route = NORTHBOUND_ROUTE
                else:
                    self.direction = 0
                    self.current_route = SOUTHBOUND_ROUTE
                self.current_index = 0
            
            # Travel to next station
            yield self.env.timeout(TRAVEL_TIME)


def parse_time(time_str):
    """Parse time string 'HH:MM:SS:mmm' to seconds."""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def run_simulation(simulate_time_str):
    """Run the O-Train simulation."""
    # Parse simulation time
    simulate_time = parse_time(simulate_time_str)
    
    logger.info(f"Starting O-Train simulation for {simulate_time} seconds")
    
    # Create simpy environment
    env = simpy.Environment()
    
    # Create station queues
    station_queues = {station_id: StationQueue(env, station_id) for station_id in STATIONS.keys()}
    
    # Create passenger generators for each station
    for station_id in STATIONS.keys():
        generator = PassengerGenerator(env, station_id, station_queues[station_id])
        env.process(generator.run())
    
    # Create train
    train = Train(env, station_queues)
    env.process(train.run())
    
    # Run simulation
    env.run(until=simulate_time)
    
    logger.info(f"Simulation completed at t={env.now:.3f} seconds")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='O-Train Light Rail Simulation')
    parser.add_argument(
        '--simulate_time',
        type=str,
        default='00:01:00:000',
        help='Simulation duration in HH:MM:SS:mmm format (default: 00:01:00:000)'
    )
    
    args = parser.parse_args()
    
    # Set random seed using system time
    current_time_ns = time.time_ns()
    random.seed(current_time_ns)
    
    # Run simulation
    run_simulation(args.simulate_time)


if __name__ == '__main__':
    main()
