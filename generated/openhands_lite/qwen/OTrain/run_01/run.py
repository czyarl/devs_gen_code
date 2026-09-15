#!/usr/bin/env python3
"""
O-Train Light Rail Simulation
Simulates a single train moving between 5 stations with passenger generation, boarding, and alighting.
"""
import argparse
import sys
import json
import random
import time
import simpy
from collections import deque

# Set random seed using system time
random.seed(time.time_ns())

# Station configuration
STATIONS = {
    1: "Bayview",
    2: "Carling", 
    3: "Carleton",
    4: "Confed",
    5: "Greenboro"
}

# Route sequence (station_id, direction)
ROUTE = [
    (1, 0), (2, 0), (3, 0), (4, 0), (5, 1), 
    (4, 1), (3, 1), (2, 1), (1, 0)
]

# Direction constants
SOUTHBOUND = 0
NORTHBOUND = 1

def generate_passenger_id(passenger_num, origin, destination):
    """Generate passenger ID using the specified formula."""
    if passenger_num == 0 and origin == 0 and destination == 0:
        return 0  # Special case for initialization passenger
    return passenger_num * 100 + origin * 10 + destination

class Train:
    """Train scheduler that controls train movement."""
    
    def __init__(self, env, station_queues, train_queue):
        self.env = env
        self.station_queues = station_queues
        self.train_queue = train_queue
        self.current_station = 1
        self.direction = SOUTHBOUND
        
        # Start the train movement process
        env.process(self.move_train())
    
    def move_train(self):
        """Move the train along the route."""
        # Initial arrival at Bayview (station 1, direction 0)
        yield self.env.timeout(0.0)  # Immediate arrival at start
        yield self.env.process(self.arrive_at_station(1, SOUTHBOUND))
        
        # Continue with the route
        for station_id, direction in ROUTE[1:]:
            # Travel time between stations is 225 seconds
            yield self.env.timeout(225.0)
            yield self.env.process(self.arrive_at_station(station_id, direction))
    
    def arrive_at_station(self, station_id, direction):
        """Handle train arrival at a station."""
        # Record arrival event
        event = {
            "time": self.env.now,
            "event": "train_arrival",
            "entity_type": "train",
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": {
                "station": station_id,
                "direction": direction
            }
        }
        print(json.dumps(event), file=sys.stdout)
        
        # Handle boarding passengers
        yield self.env.process(self.board_passengers(station_id))
        
        # Handle alighting passengers
        yield self.env.process(self.alight_passengers(station_id))
        
        # Update current state
        self.current_station = station_id
        self.direction = direction
    
    def board_passengers(self, station_id):
        """Board passengers from the station queue."""
        queue = self.station_queues[station_id]
        boarding_count = 0
        
        # Board passengers one by one with 0.025s delay between each
        while queue and boarding_count < 10:  # Max 10 passengers per stop
            passenger = queue.popleft()
            boarding_count += 1
            
            # Delay for boarding (0.025s after arrival, then 0.025s between passengers)
            yield self.env.timeout(0.025 * boarding_count)
            
            # Record boarding event
            event = {
                "time": self.env.now,
                "event": "passenger_boarding",
                "entity_type": "station_queue",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": passenger
            }
            print(json.dumps(event), file=sys.stdout)
            
            # Add to train queue
            self.train_queue[passenger["destination"]].append(passenger)
    
    def alight_passengers(self, station_id):
        """Remove passengers destined for this station from the train."""
        # Get passengers destined for this station
        destination_queue = self.train_queue[station_id]
        alighting_count = 0
        
        # Alight passengers one by one with 0.025s delay between each
        while destination_queue and alighting_count < 10:  # Max 10 passengers per stop
            passenger = destination_queue.popleft()
            alighting_count += 1
            
            # Delay for alighting (0.025s after arrival, then 0.025s between passengers)
            yield self.env.timeout(0.025 * alighting_count)
            
            # Record exiting event
            event = {
                "time": self.env.now,
                "event": "passenger_exiting",
                "entity_type": "train_queue",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": passenger
            }
            print(json.dumps(event), file=sys.stdout)

class PassengerGenerator:
    """Generates passengers at each station."""
    
    def __init__(self, env, station_queues):
        self.env = env
        self.station_queues = station_queues
        self.passenger_counter = 0
        
        # Start generating passengers at each station
        for station_id in STATIONS:
            env.process(self.generate_passengers_at_station(station_id))
    
    def generate_passengers_at_station(self, station_id):
        """Generate passengers at a specific station."""
        # Initial passenger at t=0.5 seconds
        yield self.env.timeout(0.5)
        self.passenger_counter += 1
        passenger_id = generate_passenger_id(0, station_id, 0)  # Special case
        
        passenger = {
            "passenger_id": passenger_id,
            "passenger_num": 0,
            "origin": station_id,
            "destination": 0
        }
        
        # Record passenger generation event
        event = {
            "time": self.env.now,
            "event": "passenger_generated",
            "entity_type": "passenger_generator",
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": passenger
        }
        print(json.dumps(event), file=sys.stdout)
        
        # Add to station queue
        self.station_queues[station_id].append(passenger)
        
        # Continue generating passengers
        while True:
            # Generate interval using normal distribution (mean=5min, std=5min)
            # Clamp to [1, 9] minutes then convert to seconds
            interval_minutes = random.normalvariate(5.0, 5.0)
            interval_minutes = max(1.0, min(9.0, interval_minutes))
            interval_seconds = round(interval_minutes * 60)
            
            # Wait for the interval
            yield self.env.timeout(interval_seconds)
            
            # Generate new passenger
            self.passenger_counter += 1
            # Select random destination (different from origin)
            destinations = [sid for sid in STATIONS if sid != station_id]
            destination = random.choice(destinations)
            passenger_id = generate_passenger_id(self.passenger_counter, station_id, destination)
            
            passenger = {
                "passenger_id": passenger_id,
                "passenger_num": self.passenger_counter,
                "origin": station_id,
                "destination": destination
            }
            
            # Record passenger generation event
            event = {
                "time": self.env.now,
                "event": "passenger_generated",
                "entity_type": "passenger_generator",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": passenger
            }
            print(json.dumps(event), file=sys.stdout)
            
            # Add to station queue
            self.station_queues[station_id].append(passenger)

def main():
    """Main simulation function."""
    parser = argparse.ArgumentParser(description='O-Train Light Rail Simulation')
    parser.add_argument('--simulate_time', 
                       default='00:01:00:000',
                       help='Simulation duration in HH:MM:SS:mmm. Default: 00:01:00:000')
    
    args = parser.parse_args()
    
    # Parse simulate_time
    try:
        hours, minutes, seconds, milliseconds = map(int, args.simulate_time.split(':'))
        simulate_duration = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
    except ValueError:
        print("Invalid simulate_time format. Using default 1 minute.", file=sys.stderr)
        simulate_duration = 60.0
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Initialize station queues (one per station)
    station_queues = {sid: deque() for sid in STATIONS}
    
    # Initialize train queue (one queue per destination)
    train_queue = {sid: deque() for sid in STATIONS}
    
    # Create components
    train = Train(env, station_queues, train_queue)
    passenger_generator = PassengerGenerator(env, station_queues)
    
    # Run simulation for specified duration
    env.run(until=simulate_duration)
    
    # Print final status
    print(json.dumps({
        "time": simulate_duration,
        "event": "simulation_end",
        "entity_type": "system",
        "station_id": 0,
        "station": "System",
        "payload": {
            "duration": simulate_duration,
            "passenger_count": passenger_generator.passenger_counter
        }
    }), file=sys.stdout)

if __name__ == "__main__":
    main()