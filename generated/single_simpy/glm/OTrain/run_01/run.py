import argparse
import sys
import json
import logging
import random
import time
import math
import simpy

# Setup logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# Station Configuration
STATIONS = {
    1: "Bayview",
    2: "Carling",
    3: "Carleton",
    4: "Confed",
    5: "Greenboro"
}

# Constants
TRAVEL_TIME = 225.0  # seconds between stations
BOARDING_DELAY = 0.025  # seconds per passenger
ALIGHTING_DELAY = 0.025  # seconds per passenger

# Directions
DIR_SOUTHBOUND = 0
DIR_NORTHBOUND = 1

def parse_time(time_str):
    """Parses HH:MM:SS:mmm to seconds."""
    try:
        parts = time_str.split(':')
        if len(parts) != 4:
            raise ValueError("Invalid time format")
        h = int(parts[0])
        m = int(parts[1])
        s = int(parts[2])
        ms = int(parts[3])
        return h * 3600 + m * 60 + s + ms / 1000.0
    except Exception as e:
        logger.error(f"Error parsing time string '{time_str}': {e}")
        return 60.0  # Default fallback

class Simulation:
    def __init__(self, env, sim_duration):
        self.env = env
        self.sim_duration = sim_duration
        self.passenger_counter = 0
        self.train_passengers = [] # List of passenger dicts currently on train
        self.queues = {sid: [] for sid in STATIONS.keys()} # Station queues (FIFO)
        
        # Initialize Passenger Generators
        for sid in STATIONS:
            env.process(self.passenger_generator(sid))

        # Initialize Train
        env.process(self.train_controller())

    def log_event(self, event_type, entity_type, station_id, payload):
        """Helper to print JSONL to stdout."""
        event_obj = {
            "time": round(self.env.now, 3),
            "event": event_type,
            "entity_type": entity_type,
            "station_id": station_id,
            "station": STATIONS[station_id],
            "payload": payload
        }
        # Using print with flush=True to ensure immediate output
        print(json.dumps(event_obj), flush=True)

    def passenger_generator(self, origin_id):
        """Generates passengers at a specific station."""
        # Initial passenger at t=0.5
        yield self.env.timeout(0.5)
        
        # Initial passenger ID is 0
        dest_id = self.get_random_destination(origin_id)
        passenger = {
            "passenger_id": 0,
            "passenger_num": 0,
            "origin": origin_id,
            "destination": dest_id
        }
        self.queues[origin_id].append(passenger)
        self.log_event("passenger_generated", "passenger_generator", origin_id, passenger)

        # Loop for subsequent passengers
        while True:
            # Random interval: Normal(mean=5.0 min, std=5.0 min)
            # Convert to seconds: mean=300, std=300
            mean = 5.0 * 60
            std = 5.0 * 60
            
            delay_raw = random.gauss(mean, std)
            # Clamp to [1, 9] minutes -> [60, 540] seconds
            delay_clamped = max(60.0, min(540.0, delay_raw))
            delay_rounded = round(delay_clamped)
            
            yield self.env.timeout(delay_rounded)
            
            if self.env.now > self.sim_duration:
                break

            self.passenger_counter += 1
            dest_id = self.get_random_destination(origin_id)
            
            # Encoding: passenger_id = passenger_num * 100 + origin * 10 + destination
            p_id = self.passenger_counter * 100 + origin_id * 10 + dest_id
            
            passenger = {
                "passenger_id": p_id,
                "passenger_num": self.passenger_counter,
                "origin": origin_id,
                "destination": dest_id
            }
            
            self.queues[origin_id].append(passenger)
            self.log_event("passenger_generated", "passenger_generator", origin_id, passenger)

    def get_random_destination(self, origin_id):
        """Selects a random destination different from origin."""
        possible_dests = [sid for sid in STATIONS if sid != origin_id]
        return random.choice(possible_dests)

    def train_controller(self):
        """Controls train movement and stops."""
        # Route definition
        # Southbound: 1->2->3->4->5
        # Northbound: 5->4->3->2->1
        
        # Initial state: At Bayview (1), Direction 0 (Southbound)
        # The prompt says: "Initial Arrival: t=0.0 at Bayview (Station 1, Direction 0)."
        
        current_station = 1
        direction = DIR_SOUTHBOUND
        
        while True:
            if self.env.now > self.sim_duration:
                break
            
            # 1. Arrive at station
            yield self.env.process(self.handle_station_stop(current_station, direction))
            
            # 2. Determine next station
            if direction == DIR_SOUTHBOUND:
                if current_station == 5:
                    direction = DIR_NORTHBOUND
                    next_station = 4
                else:
                    next_station = current_station + 1
            else: # Northbound
                if current_station == 1:
                    direction = DIR_SOUTHBOUND
                    next_station = 2
                else:
                    next_station = current_station - 1
            
            # 3. Travel to next station
            yield self.env.timeout(TRAVEL_TIME)
            current_station = next_station

    def handle_station_stop(self, station_id, direction):
        """Handles alighting and boarding at a station."""
        
        # Log Arrival
        self.log_event("train_arrival", "train", station_id, {
            "station": station_id,
            "direction": direction
        })
        
        # 1. Alighting Process
        # Passengers on train destined for this station alight
        alighting_passengers = [p for p in self.train_passengers if p['destination'] == station_id]
        
        for p in alighting_passengers:
            yield self.env.timeout(ALIGHTING_DELAY)
            self.log_event("passenger_exiting", "train_queue", station_id, p)
            self.train_passengers.remove(p)
            
        # 2. Boarding Process
        # Passengers in queue at this station board
        # Copy the list to iterate safely while modifying the original queue
        queue_to_process = list(self.queues[station_id])
        self.queues[station_id].clear() # FIFO means they all board in order
        
        for p in queue_to_process:
            yield self.env.timeout(BOARDING_DELAY)
            self.log_event("passenger_boarding", "station_queue", station_id, p)
            self.train_passengers.append(p)

def main():
    # Argument parsing
    parser = argparse.ArgumentParser(description="O-Train Light Rail Simulation")
    parser.add_argument("--simulate_time", type=str, default="00:01:00:000", help="Simulation duration in HH:MM:SS:mmm")
    args = parser.parse_args()

    # Seed random
    seed_val = time.time_ns()
    random.seed(seed_val)
    
    # Parse duration
    sim_duration = parse_time(args.simulate_time)
    logger.info(f"Simulation started. Duration: {sim_duration} seconds.")
    
    # Setup SimPy environment
    env = simpy.Environment()
    
    # Run Simulation
    sim = Simulation(env, sim_duration)
    
    # Run until end
    env.run(until=sim_duration)
    
    logger.info("Simulation finished.")

if __name__ == "__main__":
    main()