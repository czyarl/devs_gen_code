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

# Train route: (station_id, direction)
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

# Constants
TRAVEL_INTERVAL = 225.0  # seconds between stations
BOARDING_DELAY = 0.025  # seconds per passenger boarding
ALIGHTING_DELAY = 0.025  # seconds per passenger alighting
INIT_PASSENGER_TIME = 0.5  # seconds for initial passengers


class EventLogger:
    """Handles logging of simulation events to stdout in JSONL format."""
    
    def __init__(self):
        self.events = []
    
    def log_event(self, time, event_type, entity_type, station_id, payload):
        """Log a simulation event."""
        event = {
            "time": round(time, 3),
            "event": event_type,
            "entity_type": entity_type,
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": payload
        }
        self.events.append(event)
        print(json.dumps(event))
        sys.stdout.flush()
    
    def log_passenger_generated(self, time, passenger_id, passenger_num, origin, destination):
        """Log passenger generation event."""
        self.log_event(
            time=time,
            event_type="passenger_generated",
            entity_type="passenger_generator",
            station_id=origin,
            payload={
                "passenger_id": passenger_id,
                "passenger_num": passenger_num,
                "origin": origin,
                "destination": destination
            }
        )
    
    def log_train_arrival(self, time, station_id, direction):
        """Log train arrival event."""
        self.log_event(
            time=time,
            event_type="train_arrival",
            entity_type="train",
            station_id=station_id,
            payload={
                "station": station_id,
                "direction": direction
            }
        )
    
    def log_passenger_boarding(self, time, passenger_id, passenger_num, origin, destination):
        """Log passenger boarding event."""
        self.log_event(
            time=time,
            event_type="passenger_boarding",
            entity_type="station_queue",
            station_id=origin,
            payload={
                "passenger_id": passenger_id,
                "passenger_num": passenger_num,
                "origin": origin,
                "destination": destination
            }
        )
    
    def log_passenger_exiting(self, time, passenger_id, passenger_num, origin, destination):
        """Log passenger exiting event."""
        self.log_event(
            time=time,
            event_type="passenger_exiting",
            entity_type="train_queue",
            station_id=destination,
            payload={
                "passenger_id": passenger_id,
                "passenger_num": passenger_num,
                "origin": origin,
                "destination": destination
            }
        )


class PassengerGenerator:
    """Generates passengers at a station."""
    
    def __init__(self, env, station_id, event_logger, station_queue):
        self.env = env
        self.station_id = station_id
        self.event_logger = event_logger
        self.station_queue = station_queue
        self.passenger_num = 0
        self.action = env.process(self.run())
    
    def generate_passenger(self, is_initial=False):
        """Generate a passenger at this station."""
        if is_initial:
            passenger_id = 0
            passenger_num = 0
        else:
            self.passenger_num += 1
            passenger_num = self.passenger_num
            passenger_id = passenger_num * 100 + self.station_id * 10
        
        # Select destination (uniform from other 4 stations)
        possible_destinations = [s for s in STATIONS.keys() if s != self.station_id]
        destination = random.choice(possible_destinations)
        
        if not is_initial:
            passenger_id += destination
        
        self.event_logger.log_passenger_generated(
            time=self.env.now,
            passenger_id=passenger_id,
            passenger_num=passenger_num,
            origin=self.station_id,
            destination=destination
        )
        
        # Add passenger to station queue
        self.station_queue.add_passenger(passenger_id, passenger_num, destination)
        
        return passenger_id, passenger_num, destination
    
    def run(self):
        """Main generation process."""
        # Generate initial passenger at t=0.5
        yield self.env.timeout(INIT_PASSENGER_TIME)
        self.generate_passenger(is_initial=True)
        
        # Generate subsequent passengers
        while True:
            # Generate interval: Normal(mean=5.0 min, std=5.0 min)
            # Clamp to [1, 9] minutes, convert to seconds, round to nearest integer
            interval_minutes = random.gauss(5.0, 5.0)
            interval_minutes = max(1.0, min(9.0, interval_minutes))
            interval_seconds = int(round(interval_minutes * 60))
            
            yield self.env.timeout(interval_seconds)
            self.generate_passenger(is_initial=False)


class StationQueue:
    """Manages passengers waiting at a station."""
    
    def __init__(self, env, station_id, event_logger):
        self.env = env
        self.station_id = station_id
        self.event_logger = event_logger
        self.queue = deque()
    
    def add_passenger(self, passenger_id, passenger_num, destination):
        """Add a passenger to the queue."""
        self.queue.append({
            "passenger_id": passenger_id,
            "passenger_num": passenger_num,
            "origin": self.station_id,
            "destination": destination
        })
    
    def board_passengers(self):
        """Board passengers one by one."""
        while self.queue:
            passenger = self.queue.popleft()
            yield self.env.timeout(BOARDING_DELAY)
            self.event_logger.log_passenger_boarding(
                time=self.env.now,
                passenger_id=passenger["passenger_id"],
                passenger_num=passenger["passenger_num"],
                origin=passenger["origin"],
                destination=passenger["destination"]
            )
            # Return passenger data to be added to train
            yield passenger


class TrainQueue:
    """Manages passengers on the train."""
    
    def __init__(self, env, event_logger):
        self.env = env
        self.event_logger = event_logger
        # Passengers grouped by destination
        self.passengers_by_destination = {station_id: deque() for station_id in STATIONS.keys()}
    
    def add_passenger(self, passenger_id, passenger_num, origin, destination):
        """Add a passenger to the train."""
        self.passengers_by_destination[destination].append({
            "passenger_id": passenger_id,
            "passenger_num": passenger_num,
            "origin": origin,
            "destination": destination
        })
    
    def alight_passengers(self, station_id):
        """Alight passengers destined for this station."""
        passengers = self.passengers_by_destination[station_id]
        while passengers:
            passenger = passengers.popleft()
            yield self.env.timeout(ALIGHTING_DELAY)
            self.event_logger.log_passenger_exiting(
                time=self.env.now,
                passenger_id=passenger["passenger_id"],
                passenger_num=passenger["passenger_num"],
                origin=passenger["origin"],
                destination=passenger["destination"]
            )


class Train:
    """Controls train movement and passenger handling."""
    
    def __init__(self, env, event_logger, station_queues, train_queue):
        self.env = env
        self.event_logger = event_logger
        self.station_queues = station_queues
        self.train_queue = train_queue
        self.route_index = 0
        self.action = env.process(self.run())
    
    def run(self):
        """Main train process."""
        while True:
            station_id, direction = ROUTE_SEQUENCE[self.route_index]
            
            # Log train arrival
            self.event_logger.log_train_arrival(
                time=self.env.now,
                station_id=station_id,
                direction=direction
            )
            
            # Handle alighting first
            yield from self.train_queue.alight_passengers(station_id)
            
            # Handle boarding
            station_queue = self.station_queues[station_id]
            while station_queue.queue:
                passenger = yield from station_queue.board_passengers()
                self.train_queue.add_passenger(
                    passenger["passenger_id"],
                    passenger["passenger_num"],
                    passenger["origin"],
                    passenger["destination"]
                )
            
            # Move to next station
            yield self.env.timeout(TRAVEL_INTERVAL)
            
            # Update route index
            self.route_index = (self.route_index + 1) % len(ROUTE_SEQUENCE)


def parse_time_string(time_str):
    """Parse time string 'HH:MM:SS:mmm' to seconds."""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def main():
    """Main entry point."""
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
    
    # Set random seed using system time
    seed = time.time_ns()
    random.seed(seed)
    logger.info(f"Random seed: {seed}")
    
    # Create simpy environment
    env = simpy.Environment()
    
    # Create event logger
    event_logger = EventLogger()
    
    # Create station queues
    station_queues = {}
    for station_id in STATIONS.keys():
        station_queues[station_id] = StationQueue(env, station_id, event_logger)
    
    # Create train queue
    train_queue = TrainQueue(env, event_logger)
    
    # Create passenger generators
    for station_id in STATIONS.keys():
        PassengerGenerator(env, station_id, event_logger, station_queues[station_id])
    
    # Create train
    Train(env, event_logger, station_queues, train_queue)
    
    # Run simulation
    logger.info("Starting simulation...")
    env.run(until=simulate_time)
    logger.info(f"Simulation completed. Total events: {len(event_logger.events)}")


if __name__ == '__main__':
    main()
