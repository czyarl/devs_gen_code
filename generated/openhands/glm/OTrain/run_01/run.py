#!/usr/bin/env python3
"""
O-Train Light Rail Simulation
Discrete Event Simulation using simpy
"""

import argparse
import sys
import json
import logging
import random
import time
import simpy
from collections import deque

# Station configuration
STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro"
}

# Route configuration
# Southbound (direction 0): Bayview → Greenboro
# Northbound (direction 1): Greenboro → Bayview
SOUTHBOUND_ROUTE = [1, 2, 3, 4, 5]
NORTHBOUND_ROUTE = [5, 4, 3, 2, 1]

# Travel time between consecutive stations (seconds)
TRAVEL_TIME = 225

# Boarding/alighting delay per passenger (seconds)
PASSENGER_DELAY = 0.025

# Passenger generation parameters (in minutes)
GEN_MEAN = 5.0
GEN_STD = 5.0
GEN_MIN = 1.0
GEN_MAX = 9.0


class TrainSimulation:
    """Main simulation class for O-Train system"""
    
    def __init__(self, simulate_time_seconds):
        self.env = simpy.Environment()
        self.simulate_time = simulate_time_seconds
        
        # Station queues (FIFO) - passengers waiting to board
        self.station_queues = {station_id: deque() for station_id in STATIONS}
        
        # Train passengers - organized by destination station
        self.train_passengers = {station_id: deque() for station_id in STATIONS}
        
        # Passenger counters for each station
        self.passenger_counters = {station_id: 0 for station_id in STATIONS}
        
        # Track train state
        self.current_direction = 0  # Start southbound
        self.current_route_index = 0
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            stream=sys.stderr
        )
        self.logger = logging.getLogger(__name__)
    
    def print_event(self, event_data):
        """Print event to stdout as JSONL"""
        print(json.dumps(event_data), file=sys.stdout, flush=True)
    
    def generate_passenger_id(self, passenger_num, origin, destination):
        """Generate unique passenger ID"""
        return passenger_num * 100 + origin * 10 + destination
    
    def train_process(self):
        """Train movement and operations process"""
        while True:
            # Determine current station based on direction and route index
            if self.current_direction == 0:  # Southbound
                current_station = SOUTHBOUND_ROUTE[self.current_route_index]
            else:  # Northbound
                current_station = NORTHBOUND_ROUTE[self.current_route_index]
            
            # Generate train arrival event (at the exact arrival time)
            arrival_event = {
                "time": round(self.env.now, 3),
                "event": "train_arrival",
                "entity_type": "train",
                "station_id": current_station,
                "station": STATIONS[current_station],
                "payload": {
                    "station": current_station,
                    "direction": self.current_direction
                }
            }
            self.print_event(arrival_event)
            
            # Handle passenger alighting (exiting)
            yield from self.handle_alighting(current_station)
            
            # Handle passenger boarding
            yield from self.handle_boarding(current_station)
            
            # Update route index and direction
            if self.current_direction == 0:  # Southbound
                if self.current_route_index < len(SOUTHBOUND_ROUTE) - 1:
                    self.current_route_index += 1
                else:
                    # Switch to northbound
                    self.current_direction = 1
                    self.current_route_index = 1  # Skip Greenboro (already there)
            else:  # Northbound
                if self.current_route_index < len(NORTHBOUND_ROUTE) - 1:
                    self.current_route_index += 1
                else:
                    # Switch to southbound
                    self.current_direction = 0
                    self.current_route_index = 1  # Skip Bayview (already there)
            
            # Travel to next station
            yield self.env.timeout(TRAVEL_TIME)
    
    def handle_alighting(self, station_id):
        """Handle passengers exiting the train at a station"""
        passengers_exiting = list(self.train_passengers[station_id])
        
        for i, passenger in enumerate(passengers_exiting):
            # Delay before each passenger exits
            delay = (i + 1) * PASSENGER_DELAY
            yield self.env.timeout(delay)
            
            # Remove from train
            self.train_passengers[station_id].popleft()
            
            # Generate passenger exiting event
            exit_event = {
                "time": round(self.env.now, 3),
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
            self.print_event(exit_event)
    
    def handle_boarding(self, station_id):
        """Handle passengers boarding the train at a station"""
        passengers_boarding = list(self.station_queues[station_id])
        
        for i, passenger in enumerate(passengers_boarding):
            # Delay before each passenger boards
            delay = (i + 1) * PASSENGER_DELAY
            yield self.env.timeout(delay)
            
            # Remove from station queue
            self.station_queues[station_id].popleft()
            
            # Add to train (organized by destination)
            self.train_passengers[passenger["destination"]].append(passenger)
            
            # Generate passenger boarding event
            boarding_event = {
                "time": round(self.env.now, 3),
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
            self.print_event(boarding_event)
    
    def passenger_generator_process(self, station_id):
        """Generate passengers at a specific station"""
        # Generate initial passenger at t=0.5
        yield self.env.timeout(0.5)
        
        # Get destination for initial passenger
        destination = self._get_random_destination(station_id)
        
        # Exception: Initial passengers have passenger_id=0
        initial_passenger = {
            "passenger_id": 0,
            "passenger_num": 0,
            "origin": station_id,
            "destination": destination
        }
        
        # Add to station queue
        self.station_queues[station_id].append(initial_passenger)
        
        # Generate passenger generated event
        gen_event = {
            "time": round(self.env.now, 3),
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": {
                "passenger_id": initial_passenger["passenger_id"],
                "passenger_num": initial_passenger["passenger_num"],
                "origin": initial_passenger["origin"],
                "destination": initial_passenger["destination"]
            }
        }
        self.print_event(gen_event)
        
        # Generate subsequent passengers
        while True:
            # Calculate next interval
            interval_minutes = self._get_generation_interval()
            interval_seconds = round(interval_minutes * 60)
            
            yield self.env.timeout(interval_seconds)
            
            # Increment passenger counter
            self.passenger_counters[station_id] += 1
            passenger_num = self.passenger_counters[station_id]
            
            # Get destination first
            destination = self._get_random_destination(station_id)
            
            # Create passenger
            passenger = {
                "passenger_id": self.generate_passenger_id(
                    passenger_num, station_id, destination
                ),
                "passenger_num": passenger_num,
                "origin": station_id,
                "destination": destination
            }
            
            # Add to station queue
            self.station_queues[station_id].append(passenger)
            
            # Generate passenger generated event
            gen_event = {
                "time": round(self.env.now, 3),
                "event": "passenger_generated",
                "entity_type": "passenger_generator",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": {
                    "passenger_id": passenger["passenger_id"],
                    "passenger_num": passenger["passenger_num"],
                    "origin": passenger["origin"],
                    "destination": passenger["destination"]
                }
            }
            self.print_event(gen_event)
    
    def _get_generation_interval(self):
        """Generate random interval using normal distribution"""
        interval = random.gauss(GEN_MEAN, GEN_STD)
        # Clamp to [GEN_MIN, GEN_MAX]
        interval = max(GEN_MIN, min(GEN_MAX, interval))
        return interval
    
    def _get_random_destination(self, origin):
        """Get random destination different from origin"""
        destinations = [s for s in STATIONS.keys() if s != origin]
        return random.choice(destinations)
    
    def run(self):
        """Run the simulation"""
        self.logger.info(f"Starting O-Train simulation for {self.simulate_time} seconds")
        
        # Start train process
        self.env.process(self.train_process())
        
        # Start passenger generator processes for each station
        for station_id in STATIONS:
            self.env.process(self.passenger_generator_process(station_id))
        
        # Run simulation
        self.env.run(until=self.simulate_time)
        
        self.logger.info(f"Simulation completed at time {self.env.now:.3f} seconds")


def parse_time_string(time_str):
    """Parse time string 'HH:MM:SS:mmm' to seconds"""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    
    total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    return total_seconds


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='O-Train Light Rail Simulation'
    )
    parser.add_argument(
        '--simulate_time',
        type=str,
        default='00:01:00:000',
        help='Simulation duration in HH:MM:SS:mmm format (default: 00:01:00:000)'
    )
    
    args = parser.parse_args()
    
    # Parse simulation time
    simulate_time = parse_time_string(args.simulate_time)
    
    # Set random seed using system time
    seed = time.time_ns()
    random.seed(seed)
    
    # Create and run simulation
    sim = TrainSimulation(simulate_time)
    sim.run()


if __name__ == '__main__':
    main()