```python
import argparse
import sys
import json
import logging
import random
import time
import math
import simpy
from collections import deque
from typing import List, Dict, Any, Tuple

# Set up logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)

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

# Convert time string to seconds
def parse_time(time_str: str) -> float:
    h, m, s, ms = map(int, time_str.split(":"))
    return h * 3600 + m * 60 + s + ms / 1000.0

# Generate passenger ID
def generate_passenger_id(passenger_num: int, origin: int, destination: int) -> int:
    return passenger_num * 100 + origin * 10 + destination

# Generate passenger ID for initialization
def generate_initial_passenger_id(origin: int) -> int:
    return 0

# Passenger class
class Passenger:
    def __init__(self, passenger_id: int, passenger_num: int, origin: int, destination: int):
        self.passenger_id = passenger_id
        self.passenger_num = passenger_num
        self.origin = origin
        self.destination = destination

# Train class
class Train:
    def __init__(self, env: simpy.Environment, station_queues: Dict[int, simpy.Store], train_queue: simpy.Store):
        self.env = env
        self.station_queues = station_queues
        self.train_queue = train_queue
        self.current_station = 1
        self.direction = 0  # 0 = southbound, 1 = northbound
        self.passenger_count = 0
        self.passengers = []  # List of passengers currently on train

    def move_to_next_station(self):
        # Determine next station based on current direction
        current_index = ROUTE.index((self.current_station, self.direction))
        if self.direction == 0:
            # Southbound: going from 1 to 5
            if current_index < len(ROUTE) - 1:
                next_station, next_direction = ROUTE[current_index + 1]
            else:
                # Reached the end, reverse direction
                next_station, next_direction = ROUTE[0]
                self.direction = 1
        else:
            # Northbound: going from 5 to 1
            if current_index > 0:
                next_station, next_direction = ROUTE[current_index - 1]
            else:
                # Reached the end, reverse direction
                next_station, next_direction = ROUTE[-1]
                self.direction = 0

        return next_station, next_direction

    def run(self):
        while True:
            # Move to next station
            next_station, next_direction = self.move_to_next_station()
            
            # Calculate travel time (225 seconds)
            travel_time = 225.0
            
            # Wait for travel time
            yield self.env.timeout(travel_time)
            
            # Update current station and direction
            self.current_station = next_station
            self.direction = next_direction
            
            # Trigger train arrival event
            event_data = {
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
            print(json.dumps(event_data))
            sys.stdout.flush()
            
            # Handle alighting passengers
            self.handle_alighting()
            
            # Handle boarding passengers
            self.handle_boarding()

    def handle_alighting(self):
        # Remove passengers destined for current station
        passengers_to_remove = []
        for passenger in self.passengers:
            if passenger.destination == self.current_station:
                passengers_to_remove.append(passenger)
        
        # Process alighting one by one
        for i, passenger in enumerate(passengers_to_remove):
            delay = 0.025 * i  # 0.025s delay between passengers
            yield self.env.timeout(delay)
            
            # Remove from train
            self.passengers.remove(passenger)
            
            # Trigger passenger exiting event
            event_data = {
                "time": self.env.now,
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
            print(json.dumps(event_data))
            sys.stdout.flush()

    def handle_boarding(self):
        # Get passengers from the station queue
        queue = self.station_queues[self.current_station]
        
        # Process boarding one by one
        passengers_boarded = 0
        while not queue.empty() and passengers_boarded < 50:  # Max 50 passengers per stop
            # Get next passenger from queue
            passenger = yield queue.get()
            
            # Add to train
            self.passengers.append(passenger)
            
            # Trigger passenger boarding event
            event_data = {
                "time": self.env.now,
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
            print(json.dumps(event_data))
            sys.stdout.flush()
            
            passengers_boarded += 1

# Passenger generator class
class PassengerGenerator:
    def __init__(self, env: simpy.Environment, station_queues: Dict[int, simpy.Store], station_id: int):
        self.env = env
        self.station_queues = station_queues
        self.station_id = station_id
        self.passenger_num = 0

    def run(self):
        # Generate initial passenger at t=0.5
        yield self.env.timeout(0.5)
        initial_passenger_id = generate_initial_passenger_id(self.station_id)
        initial_passenger = Passenger(initial_passenger_id, 0, self.station_id, 0)
        self.station_queues[self.station_id].put(initial_passenger)
        
        # Generate subsequent passengers
        while True:
            # Generate interval using normal distribution
            mean = 5.0 * 60  # 5 minutes in seconds
            std_dev = 5.0 * 60  # 5 minutes in seconds
            interval = random.normalvariate(mean, std_dev)
            
            # Clamp interval to [1, 9] minutes
            interval = max(60, min(540, interval))
            
            # Round to nearest integer second
            interval = round(interval)
            
            # Wait for interval
            yield self.env.timeout(interval)
            
            # Generate passenger
            self.passenger_num += 1
            destinations = [i for i in range(1, 6) if i != self.station_id]
            destination = random.choice(destinations)
            passenger_id = generate_passenger_id(self.passenger_num, self.station_id, destination)
            passenger = Passenger(passenger_id, self.passenger_num, self.station_id, destination)
            
            # Add to station queue
            self.station_queues[self.station_id].put(passenger)
            
            # Trigger passenger generated event
            event_data = {
                "time": self.env.now,
                "event": "passenger_generated",
                "entity_type": "passenger_generator",
                "station_id": self.station_id,
                "station": STATIONS[self.station_id],
                "payload": {
                    "passenger_id": passenger.passenger_id,
                    "passenger_num": passenger.passenger_num,
                    "origin": passenger.origin,
                    "destination": passenger.destination
                }
            }
            print(json.dumps(event_data))
            sys.stdout.flush()

# Main simulation function
def run_simulation(simulate_time: float):
    # Set random seed
    random.seed(time.time_ns())
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create station queues
    station_queues = {i: simpy.Store(env) for i in range(1, 6)}
    
    # Create train queue
    train_queue = simpy.Store(env)
    
    # Create train
    train = Train(env, station_queues, train_queue)
    
    # Create passenger generators
    generators = []
    for station_id in range(1, 6):
        generator = PassengerGenerator(env, station_queues, station_id)
        generators.append(generator)
    
    # Start train
    env.process(train.run())
    
    # Start generators
    for generator in generators:
        env.process(generator.run())
    
    # Run simulation
    env.run(until=simulate_time)
    
    # Print final state
    final_state = {
        "time": simulate_time,
        "event": "simulation_end",
        "entity_type": "system",
        "station_id": 0,
        "station": "system",
        "payload": {
            "status": "completed"
        }
    }
    print(json.dumps(final_state))

def main():
    parser = argparse.ArgumentParser(description="O-Train Light Rail Simulation")
    parser.add_argument(
        "--simulate_time",
        type=str,
        default="00:01:00:000",
        help="Simulation duration in HH:MM:SS:mmm format"
    )
    
    args = parser.parse_args()
    
    # Parse simulate time
    simulate_time = parse_time(args.simulate_time)
    
    # Run simulation
    run_simulation(simulate_time)

if __name__ == "__main__":
    main()
</python_code>