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
    (1, 0),  # Bayview, Southbound (cycle repeats)
]

TRAVEL_INTERVAL = 225.0  # seconds between stations
BOARDING_DELAY = 0.025  # seconds per passenger boarding
ALIGHTING_DELAY = 0.025  # seconds per passenger alighting


class Passenger:
    """Represents a passenger in the system."""
    
    def __init__(self, passenger_id, passenger_num, origin, destination):
        self.passenger_id = passenger_id
        self.passenger_num = passenger_num
        self.origin = origin
        self.destination = destination
    
    def to_dict(self):
        return {
            "passenger_id": self.passenger_id,
            "passenger_num": self.passenger_num,
            "origin": self.origin,
            "destination": self.destination
        }


class Train:
    """Represents the train moving between stations."""
    
    def __init__(self, env, output_events):
        self.env = env
        self.output_events = output_events
        self.passengers = {}  # destination -> list of passengers
        self.route_index = 0
    
    def get_next_station(self):
        """Get the next station in the route."""
        station_id, direction = ROUTE_SEQUENCE[self.route_index]
        self.route_index = (self.route_index + 1) % len(ROUTE_SEQUENCE)
        return station_id, direction
    
    def add_passenger(self, passenger):
        """Add a passenger to the train."""
        if passenger.destination not in self.passengers:
            self.passengers[passenger.destination] = []
        self.passengers[passenger.destination].append(passenger)
    
    def remove_passengers_for_station(self, station_id):
        """Remove and return all passengers destined for this station."""
        passengers = self.passengers.get(station_id, [])
        self.passengers[station_id] = []
        return passengers


class Station:
    """Represents a station with a passenger queue."""
    
    def __init__(self, station_id, name):
        self.station_id = station_id
        self.name = name
        self.queue = []  # FIFO queue of passengers
        self.passenger_num = 0  # Counter for passengers generated at this station
    
    def add_passenger(self, passenger):
        """Add a passenger to the station queue."""
        self.queue.append(passenger)
    
    def get_next_passenger(self):
        """Get the next passenger from the queue (FIFO)."""
        if self.queue:
            return self.queue.pop(0)
        return None


class OTrainSimulation:
    """Main simulation class for the O-Train system."""
    
    def __init__(self, simulate_time_str="00:01:00:000"):
        # Parse simulation time
        self.simulate_time = self._parse_time(simulate_time_str)
        
        # Initialize simpy environment
        self.env = simpy.Environment()
        
        # Output events list
        self.output_events = []
        
        # Initialize stations
        self.stations = {
            station_id: Station(station_id, name)
            for station_id, name in STATIONS.items()
        }
        
        # Initialize train
        self.train = Train(self.env, self.output_events)
        
        # Global passenger counter
        self.global_passenger_num = 0
    
    def _parse_time(self, time_str):
        """Parse time string 'HH:MM:SS:mmm' to seconds."""
        parts = time_str.split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        milliseconds = int(parts[3])
        return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
    
    def _emit_event(self, event_type, entity_type, station_id, payload):
        """Emit a simulation event."""
        event = {
            "time": round(self.env.now, 3),
            "event": event_type,
            "entity_type": entity_type,
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": payload
        }
        self.output_events.append(event)
    
    def passenger_generator_process(self, station_id):
        """Generate passengers at a specific station."""
        station = self.stations[station_id]
        
        # Generate initial passenger at t=0.5
        yield self.env.timeout(0.5)
        
        # Initial passenger has ID=0 (exception to the encoding formula)
        destination = self._get_random_destination(station_id)
        initial_passenger = Passenger(0, 0, station_id, destination)
        station.add_passenger(initial_passenger)
        self._emit_event(
            "passenger_generated",
            "passenger_generator",
            station_id,
            initial_passenger.to_dict()
        )
        logger.info(f"Initial passenger generated at {station.name} (ID=0)")
        
        # Generate subsequent passengers
        while True:
            # Calculate next interval using normal distribution
            interval_minutes = random.normalvariate(5.0, 5.0)
            # Clamp to [1, 9] minutes
            interval_minutes = max(1.0, min(9.0, interval_minutes))
            # Convert to seconds and round to nearest integer
            interval_seconds = round(interval_minutes * 60)
            
            yield self.env.timeout(interval_seconds)
            
            # Generate new passenger
            self.global_passenger_num += 1
            station.passenger_num += 1
            
            destination = self._get_random_destination(station_id)
            passenger_id = self.global_passenger_num * 100 + station_id * 10 + destination
            
            passenger = Passenger(passenger_id, self.global_passenger_num, station_id, destination)
            station.add_passenger(passenger)
            
            self._emit_event(
                "passenger_generated",
                "passenger_generator",
                station_id,
                passenger.to_dict()
            )
            logger.info(f"Passenger {passenger_id} generated at {station.name} -> {STATIONS[destination]}")
    
    def _get_random_destination(self, origin):
        """Get a random destination different from origin."""
        possible_destinations = [sid for sid in STATIONS.keys() if sid != origin]
        return random.choice(possible_destinations)
    
    def train_process(self):
        """Train movement and passenger handling process."""
        # Start at Bayview (Station 1) at t=0
        while True:
            station_id, direction = self.train.get_next_station()
            station = self.stations[station_id]
            
            # Train arrives at station
            self._emit_event(
                "train_arrival",
                "train",
                station_id,
                {
                    "station": station_id,
                    "direction": direction
                }
            )
            logger.info(f"Train arrived at {station.name} (direction={direction})")
            
            # Handle alighting passengers first
            alighting_passengers = self.train.remove_passengers_for_station(station_id)
            for i, passenger in enumerate(alighting_passengers):
                yield self.env.timeout(ALIGHTING_DELAY)
                self._emit_event(
                    "passenger_exiting",
                    "train_queue",
                    station_id,
                    passenger.to_dict()
                )
                logger.info(f"Passenger {passenger.passenger_id} exited at {station.name}")
            
            # Handle boarding passengers
            while True:
                passenger = station.get_next_passenger()
                if passenger is None:
                    break
                
                # Validate passenger origin matches current station
                if passenger.origin != station_id:
                    logger.warning(f"Passenger {passenger.passenger_id} origin mismatch")
                    continue
                
                # Check if passenger is going in the right direction
                # Southbound (0): Bayview(1) -> Greenboro(5)
                # Northbound (1): Greenboro(5) -> Bayview(1)
                valid_direction = False
                if direction == 0:  # Southbound
                    if passenger.destination > station_id:
                        valid_direction = True
                else:  # Northbound
                    if passenger.destination < station_id:
                        valid_direction = True
                
                if not valid_direction:
                    # Put passenger back in queue (they'll wait for the right direction)
                    station.queue.insert(0, passenger)
                    break
                
                yield self.env.timeout(BOARDING_DELAY)
                self.train.add_passenger(passenger)
                self._emit_event(
                    "passenger_boarding",
                    "station_queue",
                    station_id,
                    passenger.to_dict()
                )
                logger.info(f"Passenger {passenger.passenger_id} boarded at {station.name}")
            
            # Travel to next station - ensure exactly 225 seconds from previous arrival
            # Calculate time until next arrival should be
            current_time = self.env.now
            next_arrival_time = round(current_time / TRAVEL_INTERVAL + 1) * TRAVEL_INTERVAL
            travel_delay = next_arrival_time - current_time
            
            if travel_delay > 0:
                yield self.env.timeout(travel_delay)
    
    def run(self):
        """Run the simulation."""
        logger.info(f"Starting O-Train simulation for {self.simulate_time} seconds")
        
        # Start passenger generators for all stations
        for station_id in STATIONS.keys():
            self.env.process(self.passenger_generator_process(station_id))
        
        # Start train process
        self.env.process(self.train_process())
        
        # Run simulation
        self.env.run(until=self.simulate_time)
        
        logger.info(f"Simulation completed. Total events: {len(self.output_events)}")
        
        # Output events as JSONL
        for event in self.output_events:
            print(json.dumps(event))


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="O-Train Light Rail Simulation")
    parser.add_argument(
        "--simulate_time",
        type=str,
        default="00:01:00:000",
        help="Simulation duration in HH:MM:SS:mmm format"
    )
    
    args = parser.parse_args()
    
    # Set random seeds using system time
    current_time_ns = time.time_ns()
    random.seed(current_time_ns)
    np.random.seed(current_time_ns % (2**32 - 1))
    
    logger.info(f"Random seed set to: {current_time_ns}")
    
    # Create and run simulation
    sim = OTrainSimulation(args.simulate_time)
    sim.run()


if __name__ == "__main__":
    main()