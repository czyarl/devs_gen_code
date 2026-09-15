#!/usr/bin/env python3
"""
Airfreight Logistics Operations Simulation
"""

import argparse
import json
import sys
import logging
from collections import deque
from typing import Dict, List, Optional
import simpy


# Global simulation environment
env = simpy.Environment()

# Global variables for tracking
pallet_counter = 0
expired_pallets = 0
delivered_pallets = 0
aircraft_states = {}  # aircraft_id -> state
aircraft_assignments = {}  # aircraft_id -> current pallet_id
aircraft_next_maintenance = {}  # aircraft_id -> next maintenance time
aircraft_flight_times = {}  # aircraft_id -> flight time
aircraft_unload_times = {}  # aircraft_id -> unload time
aircraft_return_times = {}  # aircraft_id -> return time
aircraft_maintenance_times = {}  # aircraft_id -> maintenance time

# Event queue for tracking
event_queue = []

def log_event(time: float, entity: str, event: str, payload: Dict):
    """Log an event to stdout in JSONL format"""
    event_obj = {
        "time": time,
        "entity": entity,
        "event": event,
        "payload": payload
    }
    print(json.dumps(event_obj))
    sys.stderr.write(f"[{time:.1f}] {entity}.{event}: {payload}\n")
    sys.stderr.flush()

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
            # Create new pallet
            self.pallet_id_counter += 1
            pallet_id = self.pallet_id_counter
            expiration_time = self.env.now + self.pallet_expiration_time
            
            # Log pallet generation
            log_event(self.env.now, "facility", "pallet_generated", {
                "pallet_id": pallet_id,
                "expiration_time": expiration_time
            })
            
            # Add to queue
            self.queue.add_pallet(pallet_id, expiration_time)
            
            # Wait for next pallet generation
            yield self.env.timeout(self.pallet_interval)

class LoadingQueue:
    """Holds incoming pallets awaiting aircraft assignment"""
    
    def __init__(self, env):
        self.env = env
        self.pallets = deque()  # (pallet_id, expiration_time)
        self.size = 0
        
    def add_pallet(self, pallet_id: int, expiration_time: float):
        """Add a pallet to the queue"""
        self.pallets.append((pallet_id, expiration_time))
        self.size += 1
        
        # Log pallet queued
        log_event(self.env.now, "queue", "pallet_queued", {
            "pallet_id": pallet_id,
            "queue_size": self.size
        })
        
    def get_pallet(self) -> Optional[tuple]:
        """Get the next pallet from the queue (FIFO)"""
        if self.pallets:
            pallet_id, expiration_time = self.pallets.popleft()
            self.size -= 1
            return pallet_id, expiration_time
        return None
        
    def check_expiration(self):
        """Check for expired pallets"""
        global expired_pallets
        
        # Create a list of expired pallets to remove
        expired_pallets_to_remove = []
        
        # Check all pallets in queue
        for pallet_id, expiration_time in self.pallets:
            if self.env.now >= expiration_time:
                expired_pallets_to_remove.append((pallet_id, expiration_time))
        
        # Remove expired pallets
        for pallet_id, expiration_time in expired_pallets_to_remove:
            self.pallets.remove((pallet_id, expiration_time))
            self.size -= 1
            expired_pallets += 1
            
            # Log pallet expiration
            log_event(self.env.now, "queue", "pallet_expired", {
                "pallet_id": pallet_id,
                "total_expired": expired_pallets
            })

class FleetCoordinator:
    """Monitors aircraft availability and cargo demand"""
    
    def __init__(self, env, queue, aircraft_list):
        self.env = env
        self.queue = queue
        self.aircraft_list = aircraft_list
        
    def assign_pallets(self):
        """Assign pallets to available aircraft"""
        while True:
            # Check if there are pallets in queue and aircraft available
            if self.queue.pallets and any(not aircraft.is_busy for aircraft in self.aircraft_list):
                # Get next pallet from queue
                pallet_info = self.queue.get_pallet()
                if pallet_info:
                    pallet_id, expiration_time = pallet_info
                    
                    # Find an idle aircraft
                    assigned_aircraft = None
                    for aircraft in self.aircraft_list:
                        if not aircraft.is_busy:
                            assigned_aircraft = aircraft
                            break
                    
                    if assigned_aircraft:
                        # Assign pallet to aircraft
                        assigned_aircraft.assign_pallet(pallet_id, expiration_time)
                        
                        # Log assignment
                        log_event(self.env.now, "coordinator", "assignment_created", {
                            "aircraft_id": assigned_aircraft.id,
                            "pallet_id": pallet_id
                        })
            
            # Check for expired pallets
            self.queue.check_expiration()
            
            # Wait a bit before next check
            yield self.env.timeout(0.1)

class Aircraft:
    """Represents an aircraft in the fleet"""
    
    def __init__(self, env, id: int, flight_time: float, unload_time: float, 
                 return_time: float, maintenance_time: float):
        self.env = env
        self.id = id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.is_busy = False
        self.current_pallet_id = None
        self.current_expiration_time = None
        
    def assign_pallet(self, pallet_id: int, expiration_time: float):
        """Assign a pallet to this aircraft"""
        self.is_busy = True
        self.current_pallet_id = pallet_id
        self.current_expiration_time = expiration_time
        
        # Start the transport cycle
        self.env.process(self.transport_cycle())
        
    def transport_cycle(self):
        """Perform the complete transport cycle"""
        # Log departure
        log_event(self.env.now, "aircraft", "depart", {
            "aircraft_id": self.id,
            "pallet_id": self.current_pallet_id
        })
        
        # Fly to destination
        yield self.env.timeout(self.flight_time)
        
        # Unload at destination
        yield self.env.timeout(self.unload_time)
        
        # Log delivery
        latency = self.env.now - self.current_expiration_time + self.flight_time + self.unload_time
        log_event(self.env.now, "destination", "pallet_delivered", {
            "pallet_id": self.current_pallet_id,
            "aircraft_id": self.id,
            "latency": latency
        })
        
        # Return to facility
        yield self.env.timeout(self.return_time)
        
        # Log return
        log_event(self.env.now, "aircraft", "return", {
            "aircraft_id": self.id
        })
        
        # Maintenance
        yield self.env.timeout(self.maintenance_time)
        
        # Log maintenance end
        log_event(self.env.now, "aircraft", "maintenance_end", {
            "aircraft_id": self.id
        })
        
        # Aircraft is now idle
        self.is_busy = False
        self.current_pallet_id = None
        self.current_expiration_time = None

def main():
    """Main simulation function"""
    global pallet_counter, expired_pallets, delivered_pallets
    
    # Parse command line arguments
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
    
    # Set up logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create entities
    queue = LoadingQueue(env)
    facility = Facility(env, queue, args.pallet_interval, args.pallet_expiration_time)
    aircraft_list = []
    
    # Create aircraft
    for i in range(args.num_aircraft):
        aircraft = Aircraft(env, i+1, args.flight_time, args.unload_time, 
                           args.return_time, args.maintenance_time)
        aircraft_list.append(aircraft)
    
    # Create coordinator
    coordinator = FleetCoordinator(env, queue, aircraft_list)
    
    # Start processes
    env.process(facility.generate_pallets())
    env.process(coordinator.assign_pallets())
    
    # Run simulation
    env.run(until=args.duration)
    
    # Print final statistics
    sys.stderr.write(f"Simulation completed. Total expired pallets: {expired_pallets}\n")
    sys.stderr.flush()

if __name__ == "__main__":
    main()