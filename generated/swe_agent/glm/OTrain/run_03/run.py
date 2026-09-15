#!/usr/bin/env python3
"""
O-Train Light Rail Simulation
Simulates the Ottawa O-Train light rail system with a single train shuttling
passengers between 5 fixed stations.
"""

import argparse
import sys
import json
import logging
import random
import time
import simpy
from collections import deque, defaultdict

# Set up logging
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

# Train route sequence: (station_id, direction)
# Direction: 0=Southbound (Bayview→Greenboro), 1=Northbound (Greenboro→Bayview)
ROUTE_SEQUENCE = [
    (1, 0),  # Bayview, Southbound
    (2, 0),  # Carling, Southbound
    (3, 0),  # Carleton, Southbound
    (4, 0),  # Confed, Southbound
    (5, 1),  # Greenboro, Northbound
    (4, 1),  # Confed, Northbound
    (3, 1),  # Carleton, Northbound
    (2, 1),  # Carling, Northbound
    (1, 0),  # Bayview, Southbound (cycle repeats)
]

TRAVEL_INTERVAL = 225.0  # seconds between stations
BOARDING_DELAY = 0.025  # seconds per passenger boarding
ALIGHTING_DELAY = 0.025  # seconds per passenger alighting


def parse_time_string(time_str):
    """Parse time string 'HH:MM:SS:mmm' to seconds."""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def generate_passenger_id(passenger_num, origin, destination):
    """Generate passenger ID using the formula: num*100 + origin*10 + dest."""
    return passenger_num * 100 + origin * 10 + destination


class Passenger:
    """Represents a passenger in the system."""
    
    def __init__(self, passenger_id, passenger_num, origin, destination):
        self.id = passenger_id
        self.num = passenger_num
        self.origin = origin
        self.destination = destination


class Train:
    """Represents the train moving between stations."""
    
    def __init__(self, env, output_events, station_queues):
        self.env = env
        self.output_events = output_events
        self.station_queues = station_queues
        self.passengers = defaultdict(deque)  # Passengers grouped by destination
        self.current_route_index = 0
    
    def run(self):
        """Main train process - moves between stations."""
        while True:
            station_id, direction = ROUTE_SEQUENCE[self.current_route_index]
            
            # Record train arrival event
            self.record_train_arrival(station_id, direction)
            
            # Process alighting (passengers exiting) - in parallel with boarding
            alighting_process = self.env.process(self.process_alighting(station_id))
            
            # Process boarding (passengers entering) - in parallel with alighting
            boarding_process = self.env.process(self.process_boarding(station_id))
            
            # Wait for both to complete
            yield alighting_process | boarding_process
            
            # Move to next station (fixed travel time, independent of boarding/alighting)
            yield self.env.timeout(TRAVEL_INTERVAL)
            
            # Update route index
            self.current_route_index = (self.current_route_index + 1) % len(ROUTE_SEQUENCE)
    
    def record_train_arrival(self, station_id, direction):
        """Record a train arrival event."""
        event = {
            "time": round(self.env.now, 3),
            "event": "train_arrival",
            "entity_type": "train",
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": {
                "station": station_id,
                "direction": direction
            }
        }
        self.output_events.append(event)
    
    def process_alighting(self, station_id):
        """Process passengers alighting at this station."""
        passengers_alighting = self.passengers[station_id]
        
        delay = ALIGHTING_DELAY
        for passenger in passengers_alighting:
            yield self.env.timeout(delay)
            delay = ALIGHTING_DELAY
            
            event = {
                "time": round(self.env.now, 3),
                "event": "passenger_exiting",
                "entity_type": "train_queue",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": {
                    "passenger_id": passenger.id,
                    "passenger_num": passenger.num,
                    "origin": passenger.origin,
                    "destination": passenger.destination
                }
            }
            self.output_events.append(event)
        
        # Clear the deque for this station
        self.passengers[station_id].clear()
    
    def process_boarding(self, station_id):
        """Process passengers boarding at this station."""
        queue = self.station_queues[station_id]
        
        delay = BOARDING_DELAY
        while queue:
            passenger = queue.popleft()
            yield self.env.timeout(delay)
            delay = BOARDING_DELAY
            
            # Add passenger to train
            self.passengers[passenger.destination].append(passenger)
            
            event = {
                "time": round(self.env.now, 3),
                "event": "passenger_boarding",
                "entity_type": "station_queue",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": {
                    "passenger_id": passenger.id,
                    "passenger_num": passenger.num,
                    "origin": passenger.origin,
                    "destination": passenger.destination
                }
            }
            self.output_events.append(event)


class PassengerGenerator:
    """Generates passengers at stations."""
    
    def __init__(self, env, station_id, output_events, station_queues):
        self.env = env
        self.station_id = station_id
        self.output_events = output_events
        self.station_queues = station_queues
        self.passenger_num = 0
    
    def run(self):
        """Main passenger generation process."""
        # Generate initial passenger at t=0.5
        yield self.env.timeout(0.5)
        self.generate_initial_passenger()
        
        # Generate subsequent passengers
        while True:
            # Calculate next interval
            interval = self.calculate_interval()
            yield self.env.timeout(interval)
            
            # Generate passenger
            self.generate_passenger()
    
    def generate_initial_passenger(self):
        """Generate the initial passenger (ID=0)."""
        passenger_id = 0
        passenger_num = 0
        origin = self.station_id
        
        # Select destination (uniform from other 4 stations)
        possible_destinations = [s for s in STATIONS.keys() if s != origin]
        destination = random.choice(possible_destinations)
        
        passenger = Passenger(passenger_id, passenger_num, origin, destination)
        
        # Add to station queue
        self.station_queues[origin].append(passenger)
        
        # Record event
        event = {
            "time": round(self.env.now, 3),
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": origin,
            "station": STATIONS[origin],
            "payload": {
                "passenger_id": passenger_id,
                "passenger_num": passenger_num,
                "origin": origin,
                "destination": destination
            }
        }
        self.output_events.append(event)
        
        logger.info(f"Initial passenger generated at {STATIONS[origin]} (ID={passenger_id})")
    
    def generate_passenger(self):
        """Generate a regular passenger."""
        self.passenger_num += 1
        passenger_num = self.passenger_num
        origin = self.station_id
        
        # Select destination (uniform from other 4 stations)
        possible_destinations = [s for s in STATIONS.keys() if s != origin]
        destination = random.choice(possible_destinations)
        
        passenger_id = generate_passenger_id(passenger_num, origin, destination)
        
        passenger = Passenger(passenger_id, passenger_num, origin, destination)
        
        # Add to station queue
        self.station_queues[origin].append(passenger)
        
        # Record event
        event = {
            "time": round(self.env.now, 3),
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": origin,
            "station": STATIONS[origin],
            "payload": {
                "passenger_id": passenger_id,
                "passenger_num": passenger_num,
                "origin": origin,
                "destination": destination
            }
        }
        self.output_events.append(event)
        
        logger.info(f"Passenger generated at {STATIONS[origin]} (ID={passenger_id}, dest={STATIONS[destination]})")
    
    def calculate_interval(self):
        """Calculate the interval until next passenger generation."""
        # Normal distribution: mean=5.0 min, std=5.0 min
        mean_minutes = 5.0
        std_minutes = 5.0
        
        interval_minutes = random.gauss(mean_minutes, std_minutes)
        
        # Clamp to [1, 9] minutes
        interval_minutes = max(1.0, min(9.0, interval_minutes))
        
        # Convert to seconds and round to nearest integer
        interval_seconds = round(interval_minutes * 60)
        
        return interval_seconds


def run_simulation(simulate_time_str):
    """Run the O-Train simulation."""
    # Parse simulation time
    simulate_time = parse_time_string(simulate_time_str)
    
    logger.info(f"Starting O-Train simulation for {simulate_time} seconds")
    
    # Create SimPy environment
    env = simpy.Environment()
    
    # Shared data structures
    output_events = []
    station_queues = {station_id: deque() for station_id in STATIONS}
    
    # Create and start train
    train = Train(env, output_events, station_queues)
    env.process(train.run())
    
    # Create and start passenger generators for each station
    for station_id in STATIONS:
        generator = PassengerGenerator(env, station_id, output_events, station_queues)
        env.process(generator.run())
    
    # Run simulation
    env.run(until=simulate_time)
    
    # Sort events by time
    output_events.sort(key=lambda e: e['time'])
    
    # Output events as JSONL
    for event in output_events:
        print(json.dumps(event))
    
    logger.info(f"Simulation completed. Generated {len(output_events)} events.")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="O-Train Light Rail Simulation"
    )
    parser.add_argument(
        '--simulate_time',
        type=str,
        default="00:01:00:000",
        help='Simulation duration in "HH:MM:SS:mmm" format (default: 00:01:00:000)'
    )
    
    args = parser.parse_args()
    
    # Set random seed using system time
    seed = time.time_ns()
    random.seed(seed)
    logger.info(f"Random seed set to: {seed}")
    
    # Run simulation
    run_simulation(args.simulate_time)


if __name__ == "__main__":
    main()