import argparse
import sys
import json
import logging
import random
import time
import math
from collections import deque
import simpy

# Set seed for reproducibility
random.seed(time.time_ns())

# Station configuration
STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro"
}

# Route configuration
ROUTE = [
    (1, 0), (2, 0), (3, 0), (4, 0), (5, 1),
    (4, 1), (3, 1), (2, 1), (1, 0)
]

# Direction constants
SOUTHBOUND = 0
NORTHBOUND = 1

# Simulation parameters
TRAIN_TRAVEL_TIME = 225  # seconds
INITIAL_PASS_GENERATION_TIME = 0.5
PASS_GENERATION_INTERVAL_MEAN = 5 * 60  # 5 minutes in seconds
PASS_GENERATION_INTERVAL_STD = 5 * 60  # 5 minutes in seconds
PASS_GENERATION_INTERVAL_MIN = 1 * 60  # 1 minute in seconds
PASS_GENERATION_INTERVAL_MAX = 9 * 60  # 9 minutes in seconds

# Boarding and alighting delays
BOARDING_ALIGHTING_DELAY = 0.025  # seconds

class Passenger:
    def __init__(self, passenger_id, passenger_num, origin, destination):
        self.passenger_id = passenger_id
        self.passenger_num = passenger_num
        self.origin = origin
        self.destination = destination

class Train:
    def __init__(self, env, station_queues, train_queue, output_queue):
        self.env = env
        self.station_queues = station_queues
        self.train_queue = train_queue
        self.output_queue = output_queue
        self.position = 0
        self.direction = SOUTHBOUND
        self.current_station = ROUTE[0][0]
        self.passenger_count = 0
        self.passenger_list = []
        
    def run(self):
        # Initial arrival at Bayview (station 1, southbound)
        yield self.env.timeout(0)
        self._handle_train_arrival()
        
        while True:
            # Move to next station
            self.position = (self.position + 1) % len(ROUTE)
            self.current_station, self.direction = ROUTE[self.position]
            
            # Wait for travel time
            yield self.env.timeout(TRAIN_TRAVEL_TIME)
            
            # Handle arrival
            self._handle_train_arrival()
            
    def _handle_train_arrival(self):
        # Log train arrival
        train_arrival_event = {
            "time": self.env.now,
            "event": "train_arrival",
            "entity_type": "train",
            "station_id": self.current_station,
            "station": STATIONS[self.current_station],
            "payload": {
                "station": self.current_station,
                "direction": self.direction
            }
        }
        self.output_queue.append(train_arrival_event)
        
        # Handle alighting
        self._handle_alighting()
        
        # Handle boarding
        self._handle_boarding()
        
    def _handle_alighting(self):
        # Remove passengers destined for current station
        new_train_queue = []
        for passenger in self.passenger_list:
            if passenger.destination == self.current_station:
                # Passenger alights
                passenger_exiting_event = {
                    "time": self.env.now + BOARDING_ALIGHTING_DELAY,
                    "event": "passenger_exiting",
                    "entity_type": "train_queue",
                    "station_id": self.current_station,
                    "station": STATIONS[self.current_station],
                    "payload": {
                        "passenger_id": passenger.passenger_id,
                        "passenger_num": passenger.passenger_num,
                        "origin": passenger.origin,
                        "destination": passenger.destination
                    }
                }
                self.output_queue.append(passenger_exiting_event)
            else:
                new_train_queue.append(passenger)
        self.passenger_list = new_train_queue
        
    def _handle_boarding(self):
        # Board passengers from the station queue
        queue = self.station_queues[self.current_station]
        passengers_to_board = []
        
        # Take all passengers from queue
        while queue:
            passenger = queue.popleft()
            if passenger.destination != self.current_station:
                passengers_to_board.append(passenger)
            else:
                # This passenger should not board at this station
                # Add back to queue (should not happen in normal flow)
                queue.append(passenger)
        
        # Board passengers one by one
        boarding_time = self.env.now
        for i, passenger in enumerate(passengers_to_board):
            boarding_time += BOARDING_ALIGHTING_DELAY * (i + 1)
            passenger_boarding_event = {
                "time": boarding_time,
                "event": "passenger_boarding",
                "entity_type": "station_queue",
                "station_id": self.current_station,
                "station": STATIONS[self.current_station],
                "payload": {
                    "passenger_id": passenger.passenger_id,
                    "passenger_num": passenger.passenger_num,
                    "origin": passenger.origin,
                    "destination": passenger.destination
                }
            }
            self.output_queue.append(passenger_boarding_event)
            self.passenger_list.append(passenger)

class PassengerGenerator:
    def __init__(self, env, station_queues, output_queue):
        self.env = env
        self.station_queues = station_queues
        self.output_queue = output_queue
        self.passenger_counter = 0
        
    def run(self):
        # Initialize passengers at all stations
        for station_id in range(1, 6):
            # Initial passenger with ID 0
            initial_passenger = Passenger(0, 0, station_id, 0)
            self._generate_passenger(initial_passenger, station_id)
            
            # Schedule future passengers
            self.env.process(self._generate_passengers_at_station(station_id))
            
    def _generate_passengers_at_station(self, station_id):
        while True:
            # Generate random interval
            interval = random.normalvariate(PASS_GENERATION_INTERVAL_MEAN, PASS_GENERATION_INTERVAL_STD)
            # Clamp to range
            interval = max(PASS_GENERATION_INTERVAL_MIN, min(PASS_GENERATION_INTERVAL_MAX, interval))
            # Round to nearest integer
            interval = round(interval)
            
            yield self.env.timeout(interval)
            
            # Generate passenger
            self.passenger_counter += 1
            destination = random.choice([s for s in range(1, 6) if s != station_id])
            passenger = Passenger(
                passenger_id=self.passenger_counter * 100 + station_id * 10 + destination,
                passenger_num=self.passenger_counter,
                origin=station_id,
                destination=destination
            )
            self._generate_passenger(passenger, station_id)
            
    def _generate_passenger(self, passenger, station_id):
        # Add to station queue
        self.station_queues[station_id].append(passenger)
        
        # Log passenger generation
        passenger_generated_event = {
            "time": self.env.now,
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": {
                "passenger_id": passenger.passenger_id,
                "passenger_num": passenger.passenger_num,
                "origin": passenger.origin,
                "destination": passenger.destination
            }
        }
        self.output_queue.append(passenger_generated_event)

def run_simulation(simulate_time):
    # Initialize simulation environment
    env = simpy.Environment()
    
    # Initialize data structures
    station_queues = {i: deque() for i in range(1, 6)}
    train_queue = []
    output_queue = []
    
    # Create components
    train = Train(env, station_queues, train_queue, output_queue)
    passenger_generator = PassengerGenerator(env, station_queues, output_queue)
    
    # Start processes
    env.process(train.run())
    env.process(passenger_generator.run())
    
    # Run simulation
    env.run(until=simulate_time)
    
    # Output events
    for event in output_queue:
        print(json.dumps(event))

def main():
    parser = argparse.ArgumentParser(description="O-Train Light Rail Simulation")
    parser.add_argument('--simulate_time', type=str, default="00:01:00:000",
                        help="Simulation duration in HH:MM:SS:mmm format")
    
    args = parser.parse_args()
    
    # Parse simulate_time
    try:
        h, m, s, ms = map(int, args.simulate_time.split(':'))
        simulate_time = h * 3600 + m * 60 + s + ms / 1000
    except ValueError:
        print("Invalid simulate_time format. Use HH:MM:SS:mmm", file=sys.stderr)
        sys.exit(1)
    
    # Run simulation
    run_simulation(simulate_time)

if __name__ == "__main__":
    main()