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
import time
import random
from collections import deque, defaultdict
import simpy

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
]

# Travel time between consecutive stations (seconds)
TRAVEL_TIME = 225

# Boarding/alighting delay per passenger (seconds)
PASSENGER_DELAY = 0.025


def parse_time_string(time_str):
    """Parse time string 'HH:MM:SS:mmm' to seconds."""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000


def generate_passenger_id(passenger_num, origin, destination):
    """Generate passenger ID using the formula: num*100 + origin*10 + dest."""
    return passenger_num * 100 + origin * 10 + destination


class OTrainSimulation:
    """Main simulation class for the O-Train system."""
    
    def __init__(self, simulate_time_seconds):
        self.simulate_time = simulate_time_seconds
        self.env = simpy.Environment()
        
        # Station queues: passengers waiting to board
        self.station_queues = {station_id: deque() for station_id in STATIONS}
        
        # Train passengers: grouped by destination
        self.train_passengers = defaultdict(deque)
        
        # Passenger counters per station
        self.passenger_counters = {station_id: 0 for station_id in STATIONS}
        
        # Track if initial passengers have been generated
        self.initial_passengers_generated = False
        
        # Track current route index
        self.route_index = 0
        
    def emit_event(self, event_type, entity_type, station_id, payload):
        """Emit a JSON event to stdout."""
        event = {
            "time": round(self.env.now, 3),
            "event": event_type,
            "entity_type": entity_type,
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": payload
        }
        print(json.dumps(event))
        sys.stdout.flush()
    
    def generate_passenger(self, station_id, is_initial=False):
        """Generate a passenger at a station."""
        if is_initial:
            passenger_num = 0
            passenger_id = 0
        else:
            self.passenger_counters[station_id] += 1
            passenger_num = self.passenger_counters[station_id]
        
        # Select destination (uniform from other stations)
        possible_destinations = [sid for sid in STATIONS if sid != station_id]
        destination = random.choice(possible_destinations)
        
        if not is_initial:
            passenger_id = generate_passenger_id(passenger_num, station_id, destination)
        
        passenger_info = {
            "passenger_id": passenger_id,
            "passenger_num": passenger_num,
            "origin": station_id,
            "destination": destination
        }
        
        # Add to station queue
        self.station_queues[station_id].append(passenger_info)
        
        # Emit event
        self.emit_event(
            "passenger_generated",
            "passenger_generator",
            station_id,
            passenger_info
        )
        
        logger.debug(f"Generated passenger {passenger_id} at station {station_id} ({STATIONS[station_id]}) -> {destination}")
    
    def passenger_generator_process(self, station_id):
        """Process that generates passengers at a station."""
        # Generate initial passenger at t=0.5
        yield self.env.timeout(0.5)
        self.generate_passenger(station_id, is_initial=True)
        
        # Generate subsequent passengers
        while True:
            # Generate interval: Normal(mean=5.0 min, std=5.0 min)
            # Clamp to [1, 9] minutes, convert to seconds, round to nearest integer
            interval_minutes = random.normalvariate(5.0, 5.0)
            interval_minutes = max(1.0, min(9.0, interval_minutes))
            interval_seconds = round(interval_minutes * 60)
            
            yield self.env.timeout(interval_seconds)
            self.generate_passenger(station_id, is_initial=False)
    
    def handle_boarding(self, station_id):
        """Handle passenger boarding at a station."""
        queue = self.station_queues[station_id]
        delay = PASSENGER_DELAY
        
        while queue:
            passenger = queue[0]  # Peek at first passenger
            
            # Validate: origin must match station
            if passenger["origin"] != station_id:
                # This shouldn't happen, but skip if it does
                queue.popleft()
                continue
            
            # Wait for boarding delay
            yield self.env.timeout(delay)
            
            # Remove from queue and add to train
            passenger = queue.popleft()
            self.train_passengers[passenger["destination"]].append(passenger)
            
            # Emit boarding event
            self.emit_event(
                "passenger_boarding",
                "station_queue",
                station_id,
                passenger
            )
            
            logger.debug(f"Passenger {passenger['passenger_id']} boarded at station {station_id}")
    
    def handle_alighting(self, station_id):
        """Handle passenger alighting at a station."""
        passengers_alighting = self.train_passengers[station_id]
        
        while passengers_alighting:
            # Wait for alighting delay
            yield self.env.timeout(PASSENGER_DELAY)
            
            # Remove from train
            passenger = passengers_alighting.popleft()
            
            # Emit exiting event
            self.emit_event(
                "passenger_exiting",
                "train_queue",
                station_id,
                passenger
            )
            
            logger.debug(f"Passenger {passenger['passenger_id']} exited at station {station_id}")
    
    def train_process(self):
        """Process that controls train movement."""
        while True:
            # Get current station and direction from route
            station_id, direction = ROUTE_SEQUENCE[self.route_index]
            
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
            
            logger.info(f"Train arrived at station {station_id} ({STATIONS[station_id]}), direction {direction}")
            
            # Handle alighting first (passengers exit)
            yield self.env.process(self.handle_alighting(station_id))
            
            # Then handle boarding (passengers enter)
            yield self.env.process(self.handle_boarding(station_id))
            
            # Move to next station in route
            self.route_index = (self.route_index + 1) % len(ROUTE_SEQUENCE)
            
            # Travel to next station
            yield self.env.timeout(TRAVEL_TIME)
    
    def run(self):
        """Run the simulation."""
        logger.info(f"Starting simulation for {self.simulate_time} seconds")
        
        # Start passenger generators for all stations
        for station_id in STATIONS:
            self.env.process(self.passenger_generator_process(station_id))
        
        # Start train process
        self.env.process(self.train_process())
        
        # Run simulation
        self.env.run(until=self.simulate_time)
        
        logger.info(f"Simulation completed at time {self.env.now}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="O-Train Light Rail Simulation"
    )
    parser.add_argument(
        "--simulate_time",
        type=str,
        default="00:01:00:000",
        help="Simulation duration in HH:MM:SS:mmm format (default: 00:01:00:000)"
    )
    
    args = parser.parse_args()
    
    # Parse simulation time
    simulate_time = parse_time_string(args.simulate_time)
    
    # Set random seed using system time
    seed = time.time_ns()
    random.seed(seed)
    logger.info(f"Random seed set to: {seed}")
    
    # Create and run simulation
    sim = OTrainSimulation(simulate_time)
    sim.run()


if __name__ == "__main__":
    main()