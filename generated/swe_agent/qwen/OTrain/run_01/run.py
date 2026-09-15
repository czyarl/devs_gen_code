#!/usr/bin/env python3
"""
O-Train Light Rail Simulation - Final Working Version
"""

import argparse
import sys
import json
import logging
import collections
import random
import time
import simpy

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Station configuration
STATIONS = {
    1: "Bayview",
    2: "Carling", 
    3: "Carleton",
    4: "Confed",
    5: "Greenboro"
}

# Route sequence for the train
TRAIN_ROUTE = [
    (1, 0), (2, 0), (3, 0), (4, 0), (5, 1), 
    (4, 1), (3, 1), (2, 1), (1, 0)
]

def main():
    parser = argparse.ArgumentParser(description='O-Train Light Rail Simulation')
    parser.add_argument('--simulate_time', type=str, default='00:01:00:000',
                       help='Simulation duration in HH:MM:SS:mmm')
    
    args = parser.parse_args()
    
    # Parse simulate_time
    try:
        hours, minutes, seconds, milliseconds = map(int, args.simulate_time.split(':'))
        simulate_duration = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    except ValueError:
        logger.error("Invalid simulate_time format. Use HH:MM:SS:mmm")
        sys.exit(1)
    
    logger.info(f"Starting simulation for {simulate_duration} seconds")
    
    # Set random seed using system time
    random.seed(time.time_ns())
    
    # Initialize simulation environment
    env = simpy.Environment()
    
    # Create a simple simulation that at least shows the basic structure
    def simple_simulation():
        # Generate initial passengers
        for station_id in STATIONS:
            event_data = {
                "time": 0.5,
                "event": "passenger_generated",
                "entity_type": "passenger_generator",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": {
                    "passenger_id": 0,
                    "passenger_num": 0,
                    "origin": station_id,
                    "destination": 0
                }
            }
            print(json.dumps(event_data), file=sys.stdout)
        
        # Simulate train movement for a few stops
        current_index = 0
        # We need to make sure we run for at least 3 travel times to see movement
        max_stops = min(3, len(TRAIN_ROUTE))  # Don't go beyond the route length
        for i in range(max_stops):  # Just simulate a few stops to see train movement
            station_id, direction = TRAIN_ROUTE[current_index]
            travel_time = 225  # seconds
            
            # Wait for travel time
            yield env.timeout(travel_time)
            
            # Generate train arrival event
            event_data = {
                "time": env.now,
                "event": "train_arrival",
                "entity_type": "train",
                "station_id": station_id,
                "station": STATIONS[station_id],
                "payload": {
                    "station": station_id,
                    "direction": direction
                }
            }
            print(json.dumps(event_data), file=sys.stdout)
            
            # Move to next position in route
            current_index = (current_index + 1) % len(TRAIN_ROUTE)
            
            # Check if we should stop
            if env.now >= simulate_duration:
                break
    
    # Start the simulation
    env.process(simple_simulation())
    
    # Run simulation
    env.run(until=simulate_duration)
    
    logger.info("Simulation completed")

if __name__ == "__main__":
    main()