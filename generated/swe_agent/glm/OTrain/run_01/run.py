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
    (1, 0),  # Bayview, Southbound (back to start)
]

# Travel time between stations (seconds)
TRAVEL_TIME = 225

# Boarding/alighting delay per passenger (seconds)
PASSENGER_DELAY = 0.025


def parse_time(time_str):
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


class Event:
    """Represents a simulation event."""
    
    def __init__(self, time, event_type, entity_type, station_id, payload):
        self.time = time
        self.event = event_type
        self.entity_type = entity_type
        self.station_id = station_id
        self.station = STATIONS[station_id]
        self.payload = payload
    
    def to_json(self):
        """Convert event to JSON object."""
        return {
            "time": round(self.time, 3),
            "event": self.event,
            "entity_type": self.entity_type,
            "station_id": self.station_id,
            "station": self.station,
            "payload": self.payload
        }


class PassengerGenerator:
    """Generates passengers at stations."""
    
    def __init__(self, env, station_id, events_list, station_queues):
        self.env = env
        self.station_id = station_id
        self.events_list = events_list
        self.station_queues = station_queues
        self.passenger_num = 0
    
    def generate_initial_passenger(self):
        """Generate initial passenger at t=0.5 seconds."""
        yield self.env.timeout(0.5)
        
        # Initial passenger has ID=0
        passenger_id = 0
        origin = self.station_id
        
        # Choose destination from other stations
        other_stations = [s for s in STATIONS.keys() if s != origin]
        destination = random.choice(other_stations)
        
        event = Event(
            time=self.env.now,
            event_type="passenger_generated",
            entity_type="passenger_generator",
            station_id=self.station_id,
            payload={
                "passenger_id": passenger_id,
                "passenger_num": 0,
                "origin": origin,
                "destination": destination
            }
        )
        self.events_list.append(event)
        
        logger.info(f"Initial passenger {passenger_id} generated at station {self.station_id} ({STATIONS[self.station_id]})")
        
        # Add passenger to station queue
        passenger_info = (passenger_id, 0, origin, destination)
        self.station_queues[origin].append(passenger_info)
        
        return passenger_id, origin, destination
    
    def generate_passengers(self):
        """Generate passengers at regular intervals."""
        # First, generate initial passenger
        yield from self.generate_initial_passenger()
        
        # Then generate regular passengers
        while True:
            # Generate interval: Normal(mean=5.0 min, std=5.0 min)
            # Clamp to [1, 9] minutes, convert to seconds, round to nearest integer
            interval_minutes = random.normalvariate(5.0, 5.0)
            interval_minutes = max(1.0, min(9.0, interval_minutes))
            interval_seconds = int(round(interval_minutes * 60))
            
            yield self.env.timeout(interval_seconds)
            
            self.passenger_num += 1
            origin = self.station_id
            
            # Choose destination from other stations
            other_stations = [s for s in STATIONS.keys() if s != origin]
            destination = random.choice(other_stations)
            
            passenger_id = generate_passenger_id(self.passenger_num, origin, destination)
            
            event = Event(
                time=self.env.now,
                event_type="passenger_generated",
                entity_type="passenger_generator",
                station_id=self.station_id,
                payload={
                    "passenger_id": passenger_id,
                    "passenger_num": self.passenger_num,
                    "origin": origin,
                    "destination": destination
                }
            )
            self.events_list.append(event)
            
            logger.info(f"Passenger {passenger_id} generated at station {self.station_id} ({STATIONS[self.station_id]})")
            
            # Add passenger to station queue
            passenger_info = (passenger_id, self.passenger_num, origin, destination)
            self.station_queues[origin].append(passenger_info)


class Train:
    """Controls train movement and passenger operations."""
    
    def __init__(self, env, station_queues, events_list):
        self.env = env
        self.station_queues = station_queues  # Dict of station_id -> queue of passengers
        self.events_list = events_list
        self.passengers_on_train = defaultdict(list)  # destination -> list of passenger_ids
        self.route_index = 0
    
    def run(self):
        """Main train operation loop."""
        while True:
            station_id, direction = ROUTE_SEQUENCE[self.route_index]
            
            # Arrive at station
            self.arrive_at_station(station_id, direction)
            
            # Move to next station in route
            self.route_index = (self.route_index + 1) % len(ROUTE_SEQUENCE)
            
            # Travel to next station (exactly 225 seconds from arrival)
            yield self.env.timeout(TRAVEL_TIME)
    
    def arrive_at_station(self, station_id, direction):
        """Handle train arrival at a station."""
        # Generate train arrival event
        event = Event(
            time=self.env.now,
            event_type="train_arrival",
            entity_type="train",
            station_id=station_id,
            payload={
                "station": station_id,
                "direction": direction
            }
        )
        self.events_list.append(event)
        
        logger.info(f"Train arrived at station {station_id} ({STATIONS[station_id]}), direction {direction}")
        
        # Handle alighting and boarding
        # These processes run but don't delay the train's departure
        # The train stays at the station for 0 seconds (instant arrival/departure)
        # Passengers board/alight in parallel with the train's schedule
        self.env.process(self.handle_alighting_async(station_id))
        self.env.process(self.handle_boarding_async(station_id, direction))
    
    def handle_alighting_async(self, station_id):
        """Handle passengers exiting the train (async process)."""
        passengers_to_exit = list(self.passengers_on_train[station_id])
        
        for i, passenger_info in enumerate(passengers_to_exit):
            # First passenger exits 0.025s after arrival, subsequent 0.025s after previous
            if i == 0:
                yield self.env.timeout(PASSENGER_DELAY)
            else:
                yield self.env.timeout(PASSENGER_DELAY)
            
            passenger_id, passenger_num, origin, destination = passenger_info
            
            event = Event(
                time=self.env.now,
                event_type="passenger_exiting",
                entity_type="train_queue",
                station_id=station_id,
                payload={
                    "passenger_id": passenger_id,
                    "passenger_num": passenger_num,
                    "origin": origin,
                    "destination": destination
                }
            )
            self.events_list.append(event)
            
            logger.info(f"Passenger {passenger_id} exited train at station {station_id} ({STATIONS[station_id]})")
        
        # Clear passengers who exited
        self.passengers_on_train[station_id] = []
    
    def handle_boarding_async(self, station_id, direction):
        """Handle passengers boarding the train (async process)."""
        # Process queue in FIFO order
        while self.station_queues[station_id]:
            passenger_info = self.station_queues[station_id][0]  # Peek at first passenger
            
            passenger_id, passenger_num, origin, destination = passenger_info
            
            # Check if passenger wants to go in the train's direction
            # Direction 0 (Southbound): Bayview(1) → Greenboro(5)
            # Direction 1 (Northbound): Greenboro(5) → Bayview(1)
            can_board = False
            if direction == 0 and destination > origin:
                can_board = True
            elif direction == 1 and destination < origin:
                can_board = True
            
            if can_board:
                # Remove from queue
                self.station_queues[station_id].popleft()
                
                # Add to train
                self.passengers_on_train[destination].append(passenger_info)
                
                # Boarding delay
                yield self.env.timeout(PASSENGER_DELAY)
                
                event = Event(
                    time=self.env.now,
                    event_type="passenger_boarding",
                    entity_type="station_queue",
                    station_id=station_id,
                    payload={
                        "passenger_id": passenger_id,
                        "passenger_num": passenger_num,
                        "origin": origin,
                        "destination": destination
                    }
                )
                self.events_list.append(event)
                
                logger.info(f"Passenger {passenger_id} boarded train at station {station_id} ({STATIONS[station_id]})")
            else:
                # Passenger can't board, stop processing queue
                break


class Simulation:
    """Main simulation controller."""
    
    def __init__(self, simulate_time_str):
        self.simulate_time = parse_time(simulate_time_str)
        self.events = []
        
        # Initialize station queues
        self.station_queues = {station_id: deque() for station_id in STATIONS}
        
        # Track generated passengers for boarding
        self.generated_passengers = defaultdict(list)  # station_id -> list of passenger_info
    
    def run(self):
        """Run the simulation."""
        # Set random seed using system time
        seed = time.time_ns()
        random.seed(seed)
        logger.info(f"Random seed set to: {seed}")
        
        # Create SimPy environment
        env = simpy.Environment()
        
        # Create passenger generators for each station
        for station_id in STATIONS:
            generator = PassengerGenerator(env, station_id, self.events, self.station_queues)
            env.process(generator.generate_passengers())
        
        # Create train
        train = Train(env, self.station_queues, self.events)
        env.process(train.run())
        
        # Run simulation
        logger.info(f"Starting simulation for {self.simulate_time} seconds")
        env.run(until=self.simulate_time)
        logger.info("Simulation completed")
        
        # Sort events by time
        self.events.sort(key=lambda e: e.time)
        
        # Output events as JSONL
        for event in self.events:
            print(json.dumps(event.to_json()))


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
    
    # Run simulation
    sim = Simulation(args.simulate_time)
    sim.run()


if __name__ == '__main__':
    main()