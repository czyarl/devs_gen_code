#!/usr/bin/env python3
"""
O-Train Light Rail Simulation
Event-driven simulation of a single train shuttling between 5 stations.
"""

import argparse
import sys
import json
import logging
import random
import time
import numpy as np
from collections import deque
import simpy


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
BOARDING_DELAY = 0.025  # seconds per passenger boarding
ALIGHTING_DELAY = 0.025  # seconds per passenger exiting
INIT_PASSENGER_TIME = 0.5  # seconds for initial passengers


def setup_logging():
    """Configure logging to stderr."""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stderr
    )


def parse_time_string(time_str):
    """Parse time string 'HH:MM:SS:mmm' to total seconds."""
    parts = time_str.split(':')
    if len(parts) == 4:
        hours, minutes, seconds, milliseconds = map(int, parts)
    elif len(parts) == 3:
        hours, minutes, seconds = map(int, parts)
        milliseconds = 0
    else:
        raise ValueError(f"Invalid time format: {time_str}")
    
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


class OTrainSimulation:
    """Main simulation class for O-Train light rail system."""
    
    def __init__(self, duration_seconds):
        self.duration = duration_seconds
        self.env = simpy.Environment()
        self.events = []
        
        # Station queues: station_id -> deque of passengers
        self.station_queues = {station_id: deque() for station_id in STATIONS}
        
        # Train passengers: destination -> deque of passengers
        self.train_passengers = {station_id: deque() for station_id in STATIONS}
        
        # Passenger counters per station
        self.passenger_counters = {station_id: 0 for station_id in STATIONS}
        
        # Track if initial passengers have been generated
        self.initial_passengers_generated = False
    
    def emit_event(self, event_type, entity_type, station_id, payload):
        """Emit a simulation event."""
        event = {
            "time": round(self.env.now, 3),
            "event": event_type,
            "entity_type": entity_type,
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": payload
        }
        self.events.append(event)
    
    def train_process(self):
        """Train movement process."""
        route_index = 0
        
        while True:
            station_id, direction = ROUTE_SEQUENCE[route_index]
            
            # Generate train arrival event
            self.emit_event(
                "train_arrival",
                "train",
                station_id,
                {
                    "station": station_id,
                    "direction": direction
                }
            )
            
            # Handle passenger alighting and boarding
            yield self.env.process(self.handle_station_stop(station_id))
            
            # Move to next station
            yield self.env.timeout(TRAVEL_INTERVAL)
            
            # Update route index (cycling through the sequence)
            route_index = (route_index + 1) % len(ROUTE_SEQUENCE)
    
    def passenger_generator_process(self, station_id):
        """Generate passengers at a specific station."""
        # Generate initial passenger at t=0.5
        yield self.env.timeout(INIT_PASSENGER_TIME)
        
        self.emit_event(
            "passenger_generated",
            "passenger_generator",
            station_id,
            {
                "passenger_id": 0,
                "passenger_num": 0,
                "origin": station_id,
                "destination": self._get_random_destination(station_id)
            }
        )
        
        # Add initial passenger to queue
        self.station_queues[station_id].append({
            "passenger_id": 0,
            "passenger_num": 0,
            "origin": station_id,
            "destination": self._get_random_destination(station_id)
        })
        
        # Generate subsequent passengers
        passenger_num = 1
        while True:
            # Calculate next generation interval
            interval_minutes = self._get_generation_interval()
            interval_seconds = int(round(interval_minutes * 60))
            
            yield self.env.timeout(interval_seconds)
            
            # Generate passenger
            destination = self._get_random_destination(station_id)
            passenger_id = passenger_num * 100 + station_id * 10 + destination
            
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
            
            # Add passenger to queue
            self.station_queues[station_id].append({
                "passenger_id": passenger_id,
                "passenger_num": passenger_num,
                "origin": station_id,
                "destination": destination
            })
            
            passenger_num += 1
    
    def _get_generation_interval(self):
        """Get random generation interval using normal distribution."""
        mean = 5.0  # minutes
        std = 5.0   # minutes
        
        interval = random.gauss(mean, std)
        # Clamp to [1, 9] minutes
        interval = max(1.0, min(9.0, interval))
        
        return interval
    
    def _get_random_destination(self, origin):
        """Get random destination different from origin."""
        destinations = [s for s in STATIONS.keys() if s != origin]
        return random.choice(destinations)
    
    def handle_station_stop(self, station_id):
        """Handle passenger alighting and boarding at a station."""
        # First, handle alighting (passengers exiting train)
        alighting_queue = self.train_passengers[station_id]
        alighting_count = len(alighting_queue)
        
        for i in range(alighting_count):
            if i == 0:
                yield self.env.timeout(ALIGHTING_DELAY)
            else:
                yield self.env.timeout(ALIGHTING_DELAY)
            
            passenger = alighting_queue.popleft()
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
        
        # Then, handle boarding (passengers entering train)
        boarding_queue = self.station_queues[station_id]
        boarding_count = len(boarding_queue)
        
        for i in range(boarding_count):
            if i == 0:
                yield self.env.timeout(BOARDING_DELAY)
            else:
                yield self.env.timeout(BOARDING_DELAY)
            
            passenger = boarding_queue.popleft()
            
            # Validate passenger origin matches station
            if passenger["origin"] == station_id:
                # Add passenger to train
                self.train_passengers[passenger["destination"]].append(passenger)
                
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
    
    def run(self):
        """Run the simulation."""
        logging.info(f"Starting O-Train simulation for {self.duration} seconds")
        
        # Start train process
        self.env.process(self.train_process())
        
        # Start passenger generators for each station
        for station_id in STATIONS:
            self.env.process(self.passenger_generator_process(station_id))
        
        # Run simulation
        self.env.run(until=self.duration)
        
        logging.info(f"Simulation completed. Generated {len(self.events)} events.")
        
        # Output events as JSONL
        for event in self.events:
            print(json.dumps(event))


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="O-Train Light Rail Simulation"
    )
    parser.add_argument(
        "--simulate_time",
        type=str,
        default="00:01:00:000",
        help="Simulation duration in HH:MM:SS:mmm format"
    )
    
    args = parser.parse_args()
    
    # Set up logging
    setup_logging()
    
    # Parse simulation time
    duration = parse_time_string(args.simulate_time)
    logging.info(f"Simulation duration: {duration} seconds")
    
    # Seed random number generators with system time
    current_time_ns = time.time_ns()
    random.seed(current_time_ns)
    np.random.seed(current_time_ns % (2**32 - 1))
    logging.info(f"Random seed: {current_time_ns}")
    
    # Create and run simulation
    sim = OTrainSimulation(duration)
    sim.run()


if __name__ == "__main__":
    main()