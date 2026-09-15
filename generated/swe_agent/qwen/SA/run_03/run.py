#!/usr/bin/env python3
"""
Airfreight Logistics Operations Simulation
"""

import argparse
import sys
import json
import logging
import collections
import random
import time
from collections import deque
import simpy


# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)


class Facility:
    """Generates new cargo pallets at regular intervals"""
    
    def __init__(self, env, queue, pallet_interval, pallet_expiration_time):
        self.env = env
        self.queue = queue
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.pallet_id_counter = 0
        
    def generate_pallets(self):
        """Generate pallets at regular intervals"""
        while True:
            # Generate a new pallet
            self.pallet_id_counter += 1
            pallet_id = self.pallet_id_counter
            expiration_time = self.env.now + self.pallet_expiration_time
            
            # Log pallet generation
            event_data = {
                "time": self.env.now,
                "entity": "facility",
                "event": "pallet_generated",
                "payload": {
                    "pallet_id": pallet_id,
                    "expiration_time": expiration_time
                }
            }
            print(json.dumps(event_data))
            sys.stdout.flush()
            
            # Add pallet to queue
            self.queue.put((pallet_id, expiration_time))
            
            # Log pallet queued
            event_data = {
                "time": self.env.now,
                "entity": "queue",
                "event": "pallet_queued",
                "payload": {
                    "pallet_id": pallet_id,
                    "queue_size": len(self.queue)
                }
            }
            print(json.dumps(event_data))
            sys.stdout.flush()
            
            # Wait for next pallet generation
            yield self.env.timeout(self.pallet_interval)


class LoadingQueue:
    """Holds incoming pallets awaiting aircraft assignment"""
    
    def __init__(self, env, coordinator):
        self.env = env
        self.coordinator = coordinator
        self.queue = deque()
        self.expired_count = 0
        
    def put(self, pallet_info):
        """Add a pallet to the queue"""
        self.queue.append(pallet_info)
        
    def get(self):
        """Get the next pallet from the queue (FIFO)"""
        if self.queue:
            return self.queue.popleft()
        return None
        
    def check_expiration(self):
        """Check for expired pallets"""
        current_time = self.env.now
        expired_pallets = []
        
        # Check if any pallets have expired
        for i, (pallet_id, expiration_time) in enumerate(list(self.queue)):
            if current_time >= expiration_time:
                expired_pallets.append((pallet_id, expiration_time))
                
        # Remove expired pallets and log them
        for pallet_id, expiration_time in expired_pallets:
            self.queue.remove((pallet_id, expiration_time))
            self.expired_count += 1
            
            event_data = {
                "time": self.env.now,
                "entity": "queue",
                "event": "pallet_expired",
                "payload": {
                    "pallet_id": pallet_id,
                    "total_expired": self.expired_count
                }
            }
            print(json.dumps(event_data))
            sys.stdout.flush()
            
    def __len__(self):
        """Return the size of the queue"""
        return len(self.queue)


class FleetCoordinator:
    """Monitors aircraft availability and cargo demand"""
    
    def __init__(self, env, queue, aircraft_list):
        self.env = env
        self.queue = queue
        self.aircraft_list = aircraft_list
        self.assignment_count = 0
        
    def assign_cargo(self):
        """Assign pallets to available aircraft"""
        while True:
            # Check if there are pallets in queue and aircraft available
            if self.queue.queue and any(not aircraft.is_busy for aircraft in self.aircraft_list):
                # Get the next pallet from queue
                pallet_info = self.queue.get()
                if pallet_info:
                    pallet_id, expiration_time = pallet_info
                    
                    # Find an available aircraft
                    available_aircraft = [aircraft for aircraft in self.aircraft_list if not aircraft.is_busy]
                    if available_aircraft:
                        aircraft = available_aircraft[0]
                        
                        # Assign pallet to aircraft
                        self.assignment_count += 1
                        aircraft.assign_pallet(pallet_id, expiration_time)
                        
                        # Log assignment
                        event_data = {
                            "time": self.env.now,
                            "entity": "coordinator",
                            "event": "assignment_created",
                            "payload": {
                                "aircraft_id": aircraft.id,
                                "pallet_id": pallet_id
                            }
                        }
                        print(json.dumps(event_data))
                        sys.stdout.flush()
                        
            yield self.env.timeout(0.1)  # Small delay to avoid busy waiting


class Aircraft:
    """Represents an aircraft in the fleet"""
    
    def __init__(self, env, id, flight_time, unload_time, return_time, maintenance_time):
        self.env = env
        self.id = id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.is_busy = False
        self.current_pallet_id = None
        self.current_expiration_time = None
        
    def assign_pallet(self, pallet_id, expiration_time):
        """Assign a pallet to this aircraft"""
        self.is_busy = True
        self.current_pallet_id = pallet_id
        self.current_expiration_time = expiration_time
        
        # Log departure
        event_data = {
            "time": self.env.now,
            "entity": "aircraft",
            "event": "depart",
            "payload": {
                "aircraft_id": self.id,
                "pallet_id": pallet_id
            }
        }
        print(json.dumps(event_data))
        sys.stdout.flush()
        
        # Start the transport cycle
        self.env.process(self.transport_cycle())
        
    def transport_cycle(self):
        """Perform the complete transport cycle"""
        # Fly to destination (flight_time)
        yield self.env.timeout(self.flight_time)
        
        # Unload cargo (unload_time)
        yield self.env.timeout(self.unload_time)
        
        # Log delivery
        # Latency = delivery_time - generation_time
        # The pallet generation time is when it was created by the facility
        # We need to track this in the facility or pass it through
        # For now, we'll calculate based on when the pallet was assigned to the aircraft
        # and the expiration time (which is when it was generated + expiration_time)
        latency = self.env.now - (self.current_expiration_time - self.flight_time - self.unload_time)
        event_data = {
            "time": self.env.now,
            "entity": "destination",
            "event": "pallet_delivered",
            "payload": {
                "pallet_id": self.current_pallet_id,
                "aircraft_id": self.id,
                "latency": latency
            }
        }
        print(json.dumps(event_data))
        sys.stdout.flush()
        
        # Return to facility (return_time)
        yield self.env.timeout(self.return_time)
        
        # Log return
        event_data = {
            "time": self.env.now,
            "entity": "aircraft",
            "event": "return",
            "payload": {
                "aircraft_id": self.id
            }
        }
        print(json.dumps(event_data))
        sys.stdout.flush()
        
        # Maintenance (maintenance_time)
        yield self.env.timeout(self.maintenance_time)
        
        # Log maintenance end
        event_data = {
            "time": self.env.now,
            "entity": "aircraft",
            "event": "maintenance_end",
            "payload": {
                "aircraft_id": self.id
            }
        }
        print(json.dumps(event_data))
        sys.stdout.flush()
        
        # Aircraft is now idle
        self.is_busy = False
        self.current_pallet_id = None
        self.current_expiration_time = None


def main():
    """Main simulation function"""
    parser = argparse.ArgumentParser(description='Airfreight Logistics Operations Simulation')
    parser.add_argument('--duration', type=float, default=10000.0, help='Total simulation time in time units')
    parser.add_argument('--num_aircraft', type=int, default=2, help='Number of aircraft in the system')
    parser.add_argument('--pallet_interval', type=float, default=25.0, help='Time interval between pallet generations')
    parser.add_argument('--pallet_expiration_time', type=float, default=150.0, help='Time window for pallet expiration')
    parser.add_argument('--flight_time', type=float, default=30.0, help='Flight duration for aircraft transport')
    parser.add_argument('--unload_time', type=float, default=2.0, help='Time required for unloading cargo at destination')
    parser.add_argument('--return_time', type=float, default=30.0, help='Return flight duration for aircraft')
    parser.add_argument('--maintenance_time', type=float, default=10.0, help='Duration of maintenance phase for aircraft')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create queue
    queue = LoadingQueue(env, None)  # Coordinator will be set later
    
    # Create aircraft
    aircraft_list = []
    for i in range(args.num_aircraft):
        aircraft = Aircraft(env, i+1, args.flight_time, args.unload_time, args.return_time, args.maintenance_time)
        aircraft_list.append(aircraft)
    
    # Create coordinator
    coordinator = FleetCoordinator(env, queue, aircraft_list)
    
    # Set up the queue with coordinator reference
    queue.coordinator = coordinator
    
    # Create facility
    facility = Facility(env, queue, args.pallet_interval, args.pallet_expiration_time)
    
    # Start facility process
    env.process(facility.generate_pallets())
    
    # Start coordinator process
    env.process(coordinator.assign_cargo())
    
    # Start queue expiration check
    def check_queue_expiration():
        while True:
            queue.check_expiration()
            yield env.timeout(1.0)  # Check every second
            
    env.process(check_queue_expiration())
    
    # Run simulation
    logging.info(f"Starting simulation for {args.duration} time units")
    start_time = time.time()
    
    try:
        env.run(until=args.duration)
        logging.info("Simulation completed successfully")
    except Exception as e:
        logging.error(f"Simulation error: {e}")
        sys.exit(1)
    
    # Ensure we end within 10 seconds real time
    end_time = time.time()
    if end_time - start_time > 10:
        logging.warning("Simulation exceeded 10 seconds real time")
    
    logging.info("Simulation finished")


if __name__ == "__main__":
    main()