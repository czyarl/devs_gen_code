#!/usr/bin/env python3
"""
Airfreight Logistics Operations Simulation
"""

import argparse
import json
import sys
import simpy
from collections import deque
import logging

# Configure logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(message)s')

class Facility:
    """Generates new cargo pallets at regular intervals."""
    
    def __init__(self, env, queue, pallet_interval, pallet_expiration_time):
        self.env = env
        self.queue = queue
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.pallet_id_counter = 0
        self.process = env.process(self._generate_pallets())
    
    def _generate_pallets(self):
        """Generate pallets at regular intervals."""
        while True:
            # Generate new pallet
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
            
            # Add pallet to queue
            self.queue.add_pallet(pallet_id, expiration_time)
            
            # Wait for next pallet generation
            yield self.env.timeout(self.pallet_interval)

class LoadingQueue:
    """Holds incoming pallets awaiting aircraft assignment."""
    
    def __init__(self, env, coordinator):
        self.env = env
        self.coordinator = coordinator
        self.pallets = deque()  # FIFO queue
        self.pallet_data = {}  # Store pallet expiration times
        self.total_expired = 0
        
    def add_pallet(self, pallet_id, expiration_time):
        """Add a pallet to the queue."""
        self.pallets.append(pallet_id)
        self.pallet_data[pallet_id] = expiration_time
        
        # Log pallet queued
        event_data = {
            "time": self.env.now,
            "entity": "queue",
            "event": "pallet_queued",
            "payload": {
                "pallet_id": pallet_id,
                "queue_size": len(self.pallets)
            }
        }
        print(json.dumps(event_data))
        
        # Check if we can assign pallets
        self.coordinator.check_assignment()
    
    def remove_pallet(self, pallet_id):
        """Remove a pallet from the queue."""
        # Remove from queue
        if pallet_id in self.pallets:
            self.pallets.remove(pallet_id)
            # Remove from pallet data
            if pallet_id in self.pallet_data:
                del self.pallet_data[pallet_id]
    
    def check_expiration(self):
        """Check for expired pallets."""
        current_time = self.env.now
        expired_count = 0
        
        # Check if any pallets have expired
        expired_pallets = []
        for pallet_id, expiration_time in list(self.pallet_data.items()):
            if expiration_time <= current_time:
                expired_pallets.append(pallet_id)
        
        # Remove expired pallets
        for pallet_id in expired_pallets:
            self.pallets.remove(pallet_id)
            del self.pallet_data[pallet_id]
            self.total_expired += 1
            
            # Log pallet expiration
            event_data = {
                "time": current_time,
                "entity": "queue",
                "event": "pallet_expired",
                "payload": {
                    "pallet_id": pallet_id,
                    "total_expired": self.total_expired
                }
            }
            print(json.dumps(event_data))
            expired_count += 1
            
        return expired_count

class FleetCoordinator:
    """Monitors aircraft availability and cargo demand."""
    
    def __init__(self, env, queue, aircraft_list):
        self.env = env
        self.queue = queue
        self.aircraft_list = aircraft_list
        
    def check_assignment(self):
        """Check if we can assign pallets to aircraft."""
        # Check if there are pallets in queue and idle aircraft
        if self.queue.pallets and any(not aircraft.is_busy for aircraft in self.aircraft_list):
            # Assign the next pallet to an idle aircraft
            self.assign_pallet()
    
    def assign_pallet(self):
        """Assign the next pallet to an idle aircraft."""
        if not self.queue.pallets:
            return
            
        # Get the next pallet from queue (FIFO)
        pallet_id = self.queue.pallets[0]  # Peek at the first item
        
        # Find an idle aircraft
        idle_aircraft = None
        for aircraft in self.aircraft_list:
            if not aircraft.is_busy:
                idle_aircraft = aircraft
                break
                
        if idle_aircraft:
            # Remove pallet from queue before assignment
            self.queue.remove_pallet(pallet_id)
            
            # Log assignment
            event_data = {
                "time": self.env.now,
                "entity": "coordinator",
                "event": "assignment_created",
                "payload": {
                    "aircraft_id": idle_aircraft.id,
                    "pallet_id": pallet_id
                }
            }
            print(json.dumps(event_data))
            
            # Assign pallet to aircraft
            idle_aircraft.assign_pallet(pallet_id)
            
            # Mark aircraft as busy
            idle_aircraft.is_busy = True

class Aircraft:
    """Represents an aircraft in the fleet."""
    
    def __init__(self, env, id, flight_time, unload_time, return_time, maintenance_time, coordinator):
        self.env = env
        self.id = id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.coordinator = coordinator
        self.is_busy = False
        self.current_pallet_id = None
        self.process = None
        
    def assign_pallet(self, pallet_id):
        """Assign a pallet to this aircraft."""
        self.current_pallet_id = pallet_id
        self.process = self.env.process(self._transport_cycle())
        
    def _transport_cycle(self):
        """Perform the complete transport cycle."""
        # Log departure
        event_data = {
            "time": self.env.now,
            "entity": "aircraft",
            "event": "depart",
            "payload": {
                "aircraft_id": self.id,
                "pallet_id": self.current_pallet_id
            }
        }
        print(json.dumps(event_data))
        
        # Fly to destination
        yield self.env.timeout(self.flight_time)
        
        # Unload at destination
        yield self.env.timeout(self.unload_time)
        
        # Log delivery
        event_data = {
            "time": self.env.now,
            "entity": "destination",
            "event": "pallet_delivered",
            "payload": {
                "pallet_id": self.current_pallet_id,
                "aircraft_id": self.id,
                "latency": self.env.now - 100  # Simplified latency calculation
            }
        }
        print(json.dumps(event_data))
        
        # Return to facility
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
        
        # Maintenance
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
        
        # Mark aircraft as idle
        self.is_busy = False
        self.current_pallet_id = None
        
        # Notify coordinator that assignment is complete
        self.coordinator.check_assignment()

def main():
    parser = argparse.ArgumentParser(description='Airfreight Logistics Operations Simulation')
    parser.add_argument('--duration', type=float, default=10000.0, help='Total simulation time in time units')
    parser.add_argument('--num_aircraft', type=int, default=2, help='Number of aircraft in the system')
    parser.add_argument('--pallet_interval', type=float, default=25.0, help='Time interval between pallet generations')
    parser.add_argument('--pallet_expiration_time', type=float, default=150.0, help='Time window for pallet expiration')
    parser.add_argument('--flight_time', type=float, default=30.0, help='Flight duration for aircraft transport')
    parser.add_argument('--unload_time', type=float, default=2.0, help='Time required for unloading cargo')
    parser.add_argument('--return_time', type=float, default=30.0, help='Return flight duration for aircraft')
    parser.add_argument('--maintenance_time', type=float, default=10.0, help='Duration of maintenance phase for aircraft')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create coordinator
    coordinator = FleetCoordinator(env, None, None)  # Will be updated later
    
    # Create queue
    queue = LoadingQueue(env, coordinator)
    
    # Update coordinator with queue and aircraft list
    coordinator.queue = queue
    
    # Create aircraft
    aircraft_list = []
    for i in range(args.num_aircraft):
        aircraft = Aircraft(env, i+1, args.flight_time, args.unload_time, args.return_time, args.maintenance_time, coordinator)
        aircraft_list.append(aircraft)
        
    # Update coordinator with aircraft list
    coordinator.aircraft_list = aircraft_list
    
    # Create facility
    facility = Facility(env, queue, args.pallet_interval, args.pallet_expiration_time)
    
    # Start the simulation
    env.run(until=args.duration)
    
    # Print final statistics
    logging.info(f"Simulation completed at time {args.duration}")

if __name__ == "__main__":
    main()