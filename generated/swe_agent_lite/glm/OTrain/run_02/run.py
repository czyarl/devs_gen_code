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
from collections import deque, defaultdict

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

# Train route sequence (station_id, direction)
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

# Travel time between stations (seconds)
TRAVEL_TIME = 225.0

# Boarding/alighting delay per passenger (seconds)
PASSENGER_DELAY = 0.025

# Passenger generation parameters
GEN_MEAN_MIN = 5.0  # Mean in minutes
GEN_STD_MIN = 5.0   # Std in minutes
GEN_MIN_MIN = 1.0   # Minimum in minutes
GEN_MAX_MIN = 9.0   # Maximum in minutes


def parse_time_arg(time_str):
    """Parse time string 'HH:MM:SS:mmm' to seconds."""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    millis = int(parts[3]) if len(parts) > 3 else 0
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def generate_passenger_id(passenger_num, origin, destination):
    """Generate passenger ID using the formula: num*100 + origin*10 + dest."""
    return passenger_num * 100 + origin * 10 + destination


class Simulation:
    """Main simulation class managing all components."""
    
    def __init__(self, simulate_time):
        self.simulate_time = simulate_time
        self.env = simpy.Environment()
        self.passenger_num = 0
        self.station_queues = {station_id: deque() for station_id in STATIONS}
        self.train_passengers = defaultdict(deque)  # destination -> deque of passengers
        self.all_passengers = {}  # passenger_id -> passenger info
        
        # Seed random number generators with system time
        seed_ns = time.time_ns()
        random.seed(seed_ns)
        logger.info(f"Random seed: {seed_ns}")
        
        # Start processes
        self.env.process(self.train_process())
        for station_id in STATIONS:
            self.env.process(self.passenger_generator_process(station_id))
    
    def emit_event(self, event_type, entity_type, station_id, payload):
        """Emit a JSONL event to stdout."""
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
    
    def train_process(self):
        """Train movement and arrival process."""
        route_index = 0
        
        while True:
            station_id, direction = ROUTE_SEQUENCE[route_index]
            
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
            yield from self.handle_alighting(station_id)
            
            # Handle boarding (passengers boarding)
            yield from self.handle_boarding(station_id)
            
            # Move to next station
            route_index = (route_index + 1) % len(ROUTE_SEQUENCE)
            yield self.env.timeout(TRAVEL_TIME)
    
    def handle_alighting(self, station_id):
        """Handle passengers alighting from the train."""
        alighting_queue = self.train_passengers[station_id]
        
        for _ in range(len(alighting_queue)):
            if len(alighting_queue) == 0:
                break
            
            passenger = alighting_queue.popleft()
            
            # Wait for alighting delay
            yield self.env.timeout(PASSENGER_DELAY)
            
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
    
    def handle_boarding(self, station_id):
        """Handle passengers boarding the train."""
        boarding_queue = self.station_queues[station_id]
        
        while len(boarding_queue) > 0:
            passenger = boarding_queue.popleft()
            
            # Wait for boarding delay
            yield self.env.timeout(PASSENGER_DELAY)
            
            # Add passenger to train (grouped by destination)
            self.train_passengers[passenger["destination"]].append(passenger)
            
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
    
    def passenger_generator_process(self, station_id):
        """Generate passengers at a specific station."""
        # Generate initial passenger at t=0.5
        yield self.env.timeout(0.5)
        
        # Initial passenger (ID=0)
        initial_passenger = {
            "passenger_id": 0,
            "passenger_num": 0,
            "origin": station_id,
            "destination": self._get_random_destination(station_id)
        }
        self.all_passengers[0] = initial_passenger
        self.station_queues[station_id].append(initial_passenger)
        
        self.emit_event(
            "passenger_generated",
            "passenger_generator",
            station_id,
            {
                "passenger_id": 0,
                "passenger_num": 0,
                "origin": station_id,
                "destination": initial_passenger["destination"]
            }
        )
        
        # Generate subsequent passengers
        while True:
            # Calculate next generation interval
            interval_min = random.normalvariate(GEN_MEAN_MIN, GEN_STD_MIN)
            # Clamp to [1, 9] minutes
            interval_min = max(GEN_MIN_MIN, min(GEN_MAX_MIN, interval_min))
            # Convert to seconds and round to nearest integer
            interval_sec = int(round(interval_min * 60))
            
            yield self.env.timeout(interval_sec)
            
            # Generate new passenger
            self.passenger_num += 1
            destination = self._get_random_destination(station_id)
            passenger_id = generate_passenger_id(self.passenger_num, station_id, destination)
            
            passenger = {
                "passenger_id": passenger_id,
                "passenger_num": self.passenger_num,
                "origin": station_id,
                "destination": destination
            }
            
            self.all_passengers[passenger_id] = passenger
            self.station_queues[station_id].append(passenger)
            
            self.emit_event(
                "passenger_generated",
                "passenger_generator",
                station_id,
                {
                    "passenger_id": passenger_id,
                    "passenger_num": self.passenger_num,
                    "origin": station_id,
                    "destination": destination
                }
            )
    
    def _get_random_destination(self, origin):
        """Get a random destination different from origin."""
        destinations = [sid for sid in STATIONS if sid != origin]
        return random.choice(destinations)
    
    def run(self):
        """Run the simulation."""
        logger.info(f"Starting simulation for {self.simulate_time} seconds")
        self.env.run(until=self.simulate_time)
        logger.info(f"Simulation completed at t={self.env.now:.3f}s")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="O-Train Light Rail Simulation")
    parser.add_argument(
        "--simulate_time",
        type=str,
        default="00:01:00:000",
        help="Simulation duration in 'HH:MM:SS:mmm' format (default: 00:01:00:000)"
    )
    
    args = parser.parse_args()
    
    # Parse simulation time
    simulate_time = parse_time_arg(args.simulate_time)
    logger.info(f"Simulation time: {simulate_time} seconds")
    
    # Create and run simulation
    sim = Simulation(simulate_time)
    sim.run()


if __name__ == "__main__":
    main()
