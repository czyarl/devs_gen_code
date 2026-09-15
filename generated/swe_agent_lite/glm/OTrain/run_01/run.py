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
# Direction: 0=Southbound (Bayview->Greenboro), 1=Northbound (Greenboro->Bayview)
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
TRAVEL_TIME = 225

# Boarding/alighting delay per passenger (seconds)
PASSENGER_DELAY = 0.025


def parse_time(time_str):
    """Parse time string 'HH:MM:SS:mmm' to seconds."""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    millis = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def generate_passenger_id(passenger_num, origin, destination):
    """Generate passenger ID using the formula: num*100 + origin*10 + dest."""
    return passenger_num * 100 + origin * 10 + destination


class EventLogger:
    """Handles logging of simulation events to stdout as JSONL."""
    
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
    
    def flush(self):
        """Flush all events (already printed as they occur)."""
        pass


class Passenger:
    """Represents a passenger in the system."""
    
    def __init__(self, passenger_id, passenger_num, origin, destination):
        self.id = passenger_id
        self.passenger_num = passenger_num
        self.origin = origin
        self.destination = destination
    
    def to_dict(self):
        """Convert passenger to dictionary for payload."""
        return {
            "passenger_id": self.id,
            "passenger_num": self.passenger_num,
            "origin": self.origin,
            "destination": self.destination
        }


class Station:
    """Represents a station with a passenger queue."""
    
    def __init__(self, station_id, env, logger):
        self.id = station_id
        self.name = STATIONS[station_id]
        self.env = env
        self.logger = logger
        self.queue = deque()  # FIFO queue of passengers
        self.passenger_num = 0
    
    def add_passenger(self, passenger):
        """Add a passenger to the station queue."""
        self.queue.append(passenger)
    
    def get_next_passenger(self):
        """Get the next passenger from the queue (FIFO)."""
        if self.queue:
            return self.queue.popleft()
        return None
    
    def has_passengers(self):
        """Check if there are passengers waiting."""
        return len(self.queue) > 0


class PassengerGenerator:
    """Generates passengers at a station."""
    
    def __init__(self, station_id, env, logger, station):
        self.id = station_id
        self.env = env
        self.logger = logger
        self.station = station
        self.passenger_num = 0
        self.process = env.process(self.run())
    
    def run(self):
        """Generate passengers over time."""
        # Generate initial passenger at t=0.5
        yield self.env.timeout(0.5)
        self._generate_initial_passenger()
        
        # Continue generating passengers
        while True:
            # Calculate next interval using normal distribution
            # Mean=5.0 min, Std=5.0 min
            interval_minutes = random.normalvariate(5.0, 5.0)
            # Clamp to [1, 9] minutes
            interval_minutes = max(1.0, min(9.0, interval_minutes))
            # Convert to seconds and round to nearest integer
            interval_seconds = int(round(interval_minutes * 60))
            
            yield self.env.timeout(interval_seconds)
            self._generate_passenger()
    
    def _generate_initial_passenger(self):
        """Generate the initial passenger with ID=0."""
        passenger = Passenger(
            passenger_id=0,
            passenger_num=0,
            origin=self.id,
            destination=self._get_random_destination()
        )
        self.station.add_passenger(passenger)
        self.logger.log_event(
            time=self.env.now,
            event_type="passenger_generated",
            entity_type="passenger_generator",
            station_id=self.id,
            payload=passenger.to_dict()
        )
        self.passenger_num = 1
    
    def _generate_passenger(self):
        """Generate a regular passenger."""
        passenger = Passenger(
            passenger_id=generate_passenger_id(self.passenger_num, self.id, self._get_random_destination()),
            passenger_num=self.passenger_num,
            origin=self.id,
            destination=self._get_random_destination()
        )
        self.station.add_passenger(passenger)
        self.logger.log_event(
            time=self.env.now,
            event_type="passenger_generated",
            entity_type="passenger_generator",
            station_id=self.id,
            payload=passenger.to_dict()
        )
        self.passenger_num += 1
    
    def _get_random_destination(self):
        """Get a random destination different from origin."""
        possible_destinations = [sid for sid in STATIONS.keys() if sid != self.id]
        return random.choice(possible_destinations)


class Train:
    """Represents the train moving between stations."""
    
    def __init__(self, env, logger, stations):
        self.env = env
        self.logger = logger
        self.stations = stations
        self.passengers = []  # List of passengers on train
        self.route_index = 0
        self.process = env.process(self.run())
    
    def run(self):
        """Train operation loop."""
        # Start at Bayview (Station 1, Direction 0) at t=0.0
        while True:
            station_id, direction = ROUTE_SEQUENCE[self.route_index]
            station = self.stations[station_id]
            
            # Log train arrival
            self.logger.log_event(
                time=self.env.now,
                event_type="train_arrival",
                entity_type="train",
                station_id=station_id,
                payload={
                    "station": station_id,
                    "direction": direction
                }
            )
            
            # Handle alighting first
            yield self.env.process(self._handle_alighting(station_id))
            
            # Then handle boarding
            yield self.env.process(self._handle_boarding(station_id, direction))
            
            # Move to next station
            yield self.env.timeout(TRAVEL_TIME)
            
            # Update route index
            self.route_index = (self.route_index + 1) % len(ROUTE_SEQUENCE)
    
    def _handle_alighting(self, station_id):
        """Handle passengers alighting at the station."""
        # Find passengers destined for this station
        alighting_passengers = [p for p in self.passengers if p.destination == station_id]
        
        if alighting_passengers:
            # Remove them from train
            self.passengers = [p for p in self.passengers if p.destination != station_id]
            
            # Alight one by one with delay
            for i, passenger in enumerate(alighting_passengers):
                # First passenger alights 0.025s after arrival
                # Subsequent passengers alight 0.025s after previous
                delay = (i + 1) * PASSENGER_DELAY
                yield self.env.timeout(delay)
                
                self.logger.log_event(
                    time=self.env.now,
                    event_type="passenger_exiting",
                    entity_type="train_queue",
                    station_id=station_id,
                    payload=passenger.to_dict()
                )
    
    def _handle_boarding(self, station_id, direction):
        """Handle passengers boarding at the station."""
        station = self.stations[station_id]
        
        # Board passengers one by one with delay
        i = 0
        while station.has_passengers():
            passenger = station.get_next_passenger()
            
            # Validate passenger origin matches station
            if passenger.origin != station_id:
                continue
            
            # First passenger boards 0.025s after arrival
            # Subsequent passengers board 0.025s after previous
            delay = (i + 1) * PASSENGER_DELAY
            yield self.env.timeout(delay)
            
            self.logger.log_event(
                time=self.env.now,
                event_type="passenger_boarding",
                entity_type="station_queue",
                station_id=station_id,
                payload=passenger.to_dict()
            )
            
            # Add passenger to train
            self.passengers.append(passenger)
            i += 1


class OTrainSimulation:
    """Main simulation class."""
    
    def __init__(self, simulate_time):
        self.simulate_time = simulate_time
        self.env = simpy.Environment()
        self.logger = EventLogger()
        self.stations = {}
        self.generators = {}
        self.train = None
    
    def setup(self):
        """Setup the simulation components."""
        # Create stations
        for station_id in STATIONS:
            self.stations[station_id] = Station(station_id, self.env, self.logger)
        
        # Create passenger generators for each station
        for station_id in STATIONS:
            self.generators[station_id] = PassengerGenerator(
                station_id, self.env, self.logger, self.stations[station_id]
            )
        
        # Create train
        self.train = Train(self.env, self.logger, self.stations)
    
    def run(self):
        """Run the simulation."""
        self.env.run(until=self.simulate_time)


def main():
    """Main entry point."""
    # Setup argument parser
    parser = argparse.ArgumentParser(description="O-Train Light Rail Simulation")
    parser.add_argument(
        "--simulate_time",
        type=str,
        default="00:01:00:000",
        help="Simulation duration in HH:MM:SS:mmm format"
    )
    
    args = parser.parse_args()
    
    # Parse simulation time
    simulate_time = parse_time(args.simulate_time)
    
    # Setup logging to stderr
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        stream=sys.stderr
    )
    logger = logging.getLogger(__name__)
    
    # Seed random number generator with system time
    current_time_ns = time.time_ns()
    random.seed(current_time_ns)
    logger.info(f"Random seed: {current_time_ns}")
    
    # Create and run simulation
    logger.info(f"Starting simulation for {simulate_time} seconds")
    sim = OTrainSimulation(simulate_time)
    sim.setup()
    sim.run()
    
    logger.info(f"Simulation completed. Total events logged: {len(sim.logger.events)}")


if __name__ == "__main__":
    main()
