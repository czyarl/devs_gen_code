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
import numpy as np
import simpy
from collections import deque

# Configure logging
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

# Route sequence: (station_id, direction)
ROUTE_SEQUENCE = [
    (1, 0),  # Bayview, Southbound
    (2, 0),  # Carling, Southbound
    (3, 0),  # Carleton, Southbound
    (4, 0),  # Confed, Southbound
    (5, 1),  # Greenboro, Northbound
    (4, 1),  # Confed, Northbound
    (3, 1),  # Carleton, Northbound
    (2, 1),  # Carling, Northbound
]

# Constants
TRAVEL_INTERVAL = 225.0  # seconds between stations
BOARDING_DELAY = 0.025  # seconds per passenger
INITIAL_PASSENGER_TIME = 0.5  # seconds


class Simulation:
    """Main simulation controller"""
    
    def __init__(self, simulate_time_seconds):
        self.env = simpy.Environment()
        self.simulate_time = simulate_time_seconds
        self.events = []
        
        # Station queues: {station_id: deque of passengers}
        self.station_queues = {i: deque() for i in range(1, 6)}
        
        # Train passengers: {destination_station_id: deque of passengers}
        self.train_passengers = {i: deque() for i in range(1, 6)}
        
        # Passenger counters
        self.passenger_counters = {i: 0 for i in range(1, 6)}
        
        # Track initial passengers
        self.initial_passengers_generated = False
        
    def emit_event(self, event_type, entity_type, station_id, payload):
        """Emit a simulation event"""
        event = {
            "time": round(self.env.now, 3),
            "event": event_type,
            "entity_type": entity_type,
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": payload
        }
        self.events.append(event)
        print(json.dumps(event))
        
    def generate_passenger_id(self, passenger_num, origin, destination):
        """Generate passenger ID: num*100 + origin*10 + dest"""
        return passenger_num * 100 + origin * 10 + destination
    
    def passenger_generator_process(self, station_id):
        """Generate passengers at a station"""
        # Generate initial passenger at t=0.5
        yield self.env.timeout(INITIAL_PASSENGER_TIME)
        
        # Initial passenger (ID=0)
        self.emit_event(
            "passenger_generated",
            "passenger_generator",
            station_id,
            {
                "passenger_id": 0,
                "passenger_num": 0,
                "origin": station_id,
                "destination": 0  # Will be set when boarding
            }
        )
        self.station_queues[station_id].append({
            "passenger_id": 0,
            "passenger_num": 0,
            "origin": station_id,
            "destination": None  # Will be assigned when boarding
        })
        
        # Generate subsequent passengers
        while True:
            # Random interval: Normal(mean=5min, std=5min), clamped to [1,9] min
            interval_minutes = np.random.normal(5.0, 5.0)
            interval_minutes = max(1.0, min(9.0, interval_minutes))
            interval_seconds = int(round(interval_minutes * 60))
            
            yield self.env.timeout(interval_seconds)
            
            # Check if simulation time exceeded
            if self.env.now >= self.simulate_time:
                break
            
            # Select destination (uniform from other stations)
            possible_destinations = [i for i in range(1, 6) if i != station_id]
            destination = random.choice(possible_destinations)
            
            # Increment passenger counter
            self.passenger_counters[station_id] += 1
            passenger_num = self.passenger_counters[station_id]
            
            # Generate passenger ID
            passenger_id = self.generate_passenger_id(passenger_num, station_id, destination)
            
            # Emit event
            self.emit_event(
                "passenger_generated",
                "passenger_generator",
                station_id,
                {
                    "passenger_id": passenger_id,
                    "passenger_num": passenger_num,
                    "origin": station_id,
                    "destination": destination
                }
            )
            
            # Add to station queue
            self.station_queues[station_id].append({
                "passenger_id": passenger_id,
                "passenger_num": passenger_num,
                "origin": station_id,
                "destination": destination
            })
    
    def train_process(self):
        """Train movement and passenger handling"""
        route_index = 0
        
        while True:
            station_id, direction = ROUTE_SEQUENCE[route_index]
            
            # Check if simulation time exceeded
            if self.env.now >= self.simulate_time:
                break
            
            # Emit train arrival event
            self.emit_event(
                "train_arrival",
                "train",
                station_id,
                {
                    "station": station_id,
                    "direction": direction
                }
            )
            
            # Handle alighting (passengers exiting)
            alighting_delay = 0.0
            while self.train_passengers[station_id]:
                passenger = self.train_passengers[station_id].popleft()
                yield self.env.timeout(alighting_delay)
                
                # Emit passenger exiting event
                self.emit_event(
                    "passenger_exiting",
                    "train_queue",
                    station_id,
                    {
                        "passenger_id": passenger["passenger_id"],
                        "passenger_num": passenger["passenger_num"],
                        "origin": passenger["origin"],
                        "destination": passenger["destination"]
                    }
                )
                
                alighting_delay = BOARDING_DELAY
            
            # Handle boarding (passengers entering)
            boarding_delay = 0.0
            while self.station_queues[station_id]:
                passenger = self.station_queues[station_id].popleft()
                
                # For initial passenger (ID=0), assign destination now
                if passenger["passenger_id"] == 0:
                    possible_destinations = [i for i in range(1, 6) if i != station_id]
                    passenger["destination"] = random.choice(possible_destinations)
                
                # Validate passenger origin matches station
                if passenger["origin"] != station_id:
                    continue
                
                # Check if destination is valid
                if passenger["destination"] == station_id:
                    continue
                
                yield self.env.timeout(boarding_delay)
                
                # Emit passenger boarding event
                self.emit_event(
                    "passenger_boarding",
                    "station_queue",
                    station_id,
                    {
                        "passenger_id": passenger["passenger_id"],
                        "passenger_num": passenger["passenger_num"],
                        "origin": passenger["origin"],
                        "destination": passenger["destination"]
                    }
                )
                
                # Add passenger to train
                self.train_passengers[passenger["destination"]].append(passenger)
                
                boarding_delay = BOARDING_DELAY
            
            # Move to next station
            yield self.env.timeout(TRAVEL_INTERVAL)
            
            # Update route index
            route_index = (route_index + 1) % len(ROUTE_SEQUENCE)
    
    def run(self):
        """Run the simulation"""
        logger.info(f"Starting simulation for {self.simulate_time} seconds")
        
        # Start passenger generators for all stations
        for station_id in range(1, 6):
            self.env.process(self.passenger_generator_process(station_id))
        
        # Start train process
        self.env.process(self.train_process())
        
        # Run simulation
        self.env.run(until=self.simulate_time)
        
        logger.info(f"Simulation completed. Generated {len(self.events)} events")


def parse_time_string(time_str):
    """Parse time string 'HH:MM:SS:mmm' to seconds"""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    
    total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
    return total_seconds


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='O-Train Light Rail Simulation')
    parser.add_argument(
        '--simulate_time',
        type=str,
        default='00:01:00:000',
        help='Simulation duration in HH:MM:SS:mmm format'
    )
    
    args = parser.parse_args()
    
    # Parse simulation time
    simulate_time = parse_time_string(args.simulate_time)
    logger.info(f"Simulation time: {simulate_time} seconds")
    
    # Set random seeds using system time
    current_time_ns = time.time_ns()
    random.seed(current_time_ns)
    np.random.seed(current_time_ns % (2**32 - 1))
    logger.info(f"Random seed set using system time: {current_time_ns}")
    
    # Create and run simulation
    sim = Simulation(simulate_time)
    sim.run()


if __name__ == '__main__':
    main()