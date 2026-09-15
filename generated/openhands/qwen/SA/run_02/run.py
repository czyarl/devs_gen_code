#!/usr/bin/env python3
"""
Airfreight Logistics Operations Simulation
"""

import argparse
import sys
import json
import logging
from collections import deque
from typing import Dict, List, Optional
import simpy


# Global variables for simulation
PALLETS_GENERATED = 0
TOTAL_EXPIRED = 0
DELIVERED_PALLETS = 0
AIRCRAFT_UTILIZATION = 0


class Pallet:
    """Represents a cargo pallet with ID and expiration time."""
    
    def __init__(self, pallet_id: int, expiration_time: float):
        self.pallet_id = pallet_id
        self.expiration_time = expiration_time


class Facility:
    """Generates new cargo pallets at regular intervals."""
    
    def __init__(self, env: simpy.Environment, queue, pallet_interval: float):
        self.env = env
        self.queue = queue
        self.pallet_interval = pallet_interval
        self.pallet_id_counter = 0
        
    def generate_pallets(self):
        """Generate pallets at regular intervals."""
        while True:
            # Generate new pallet
            self.pallet_id_counter += 1
            pallet = Pallet(self.pallet_id_counter, self.env.now + 150.0)  # Default expiration
            
            # Log pallet generation
            event_data = {
                "time": self.env.now,
                "entity": "facility",
                "event": "pallet_generated",
                "payload": {
                    "pallet_id": pallet.pallet_id,
                    "expiration_time": pallet.expiration_time
                }
            }
            print(json.dumps(event_data), file=sys.stderr)
            
            # Add to queue
            self.queue.put(pallet)
            
            # Log queue event
            event_data = {
                "time": self.env.now,
                "entity": "queue",
                "event": "pallet_queued",
                "payload": {
                    "pallet_id": pallet.pallet_id,
                    "queue_size": len(self.queue.items)
                }
            }
            print(json.dumps(event_data), file=sys.stderr)
            
            # Wait for next pallet generation
            yield self.env.timeout(self.pallet_interval)


class LoadingQueue:
    """Holds incoming pallets awaiting aircraft assignment."""
    
    def __init__(self, env: simpy.Environment):
        self.env = env
        self.items = deque()
        
    def put(self, pallet: Pallet):
        """Add pallet to queue."""
        self.items.append(pallet)
        
    def get(self) -> Optional[Pallet]:
        """Get next pallet from queue (FIFO)."""
        if self.items:
            return self.items.popleft()
        return None
        
    def check_expiration(self):
        """Check for expired pallets and remove them."""
        global TOTAL_EXPIRED
        expired_pallets = []
        
        # Check all pallets in queue for expiration
        for pallet in list(self.items):
            if self.env.now >= pallet.expiration_time:
                expired_pallets.append(pallet)
                
        # Remove expired pallets
        for pallet in expired_pallets:
            self.items.remove(pallet)
            TOTAL_EXPIRED += 1
            event_data = {
                "time": self.env.now,
                "entity": "queue",
                "event": "pallet_expired",
                "payload": {
                    "pallet_id": pallet.pallet_id,
                    "total_expired": TOTAL_EXPIRED
                }
            }
            print(json.dumps(event_data), file=sys.stderr)


class FleetCoordinator:
    """Manages aircraft availability and cargo assignment."""
    
    def __init__(self, env: simpy.Environment, queue: LoadingQueue, aircraft_list: List):
        self.env = env
        self.queue = queue
        self.aircraft_list = aircraft_list
        self.assignment_count = 0
        
    def assign_cargo(self):
        """Assign pallets to available aircraft."""
        while True:
            # Check if there are pallets in queue and aircraft available
            if self.queue.items and any(not aircraft.is_busy for aircraft in self.aircraft_list):
                # Get next pallet from queue
                pallet = self.queue.get()
                
                # Find an idle aircraft
                idle_aircraft = None
                for aircraft in self.aircraft_list:
                    if not aircraft.is_busy:
                        idle_aircraft = aircraft
                        break
                        
                if idle_aircraft:
                    # Assign pallet to aircraft
                    self.assignment_count += 1
                    idle_aircraft.assign_pallet(pallet)
                    
                    event_data = {
                        "time": self.env.now,
                        "entity": "coordinator",
                        "event": "assignment_created",
                        "payload": {
                            "aircraft_id": idle_aircraft.aircraft_id,
                            "pallet_id": pallet.pallet_id
                        }
                    }
                    print(json.dumps(event_data), file=sys.stderr)
                    
            yield self.env.timeout(1)  # Check every second


class Aircraft:
    """Represents an aircraft in the fleet."""
    
    def __init__(self, env: simpy.Environment, aircraft_id: int, 
                 flight_time: float, unload_time: float, return_time: float, 
                 maintenance_time: float):
        self.env = env
        self.aircraft_id = aircraft_id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.is_busy = False
        self.current_pallet = None
        self.pallet_generation_time = None
        
    def assign_pallet(self, pallet: Pallet):
        """Assign a pallet to this aircraft."""
        self.is_busy = True
        self.current_pallet = pallet
        self.pallet_generation_time = pallet.expiration_time - 150.0  # Calculate generation time
        
        # Log departure event
        event_data = {
            "time": self.env.now,
            "entity": "aircraft",
            "event": "depart",
            "payload": {
                "aircraft_id": self.aircraft_id,
                "pallet_id": pallet.pallet_id
            }
        }
        print(json.dumps(event_data), file=sys.stderr)
        
        # Start the transport cycle
        self.env.process(self.transport_cycle())
        
    def transport_cycle(self):
        """Perform the complete transport cycle."""
        # Fly to destination
        yield self.env.timeout(self.flight_time)
        
        # Unload at destination
        yield self.env.timeout(self.unload_time)
        
        # Log delivery event
        global DELIVERED_PALLETS
        DELIVERED_PALLETS += 1
        latency = self.env.now - self.pallet_generation_time
        
        event_data = {
            "time": self.env.now,
            "entity": "destination",
            "event": "pallet_delivered",
            "payload": {
                "pallet_id": self.current_pallet.pallet_id,
                "aircraft_id": self.aircraft_id,
                "latency": latency
            }
        }
        print(json.dumps(event_data), file=sys.stderr)
        
        # Return to facility
        yield self.env.timeout(self.return_time)
        
        # Log return event
        event_data = {
            "time": self.env.now,
            "entity": "aircraft",
            "event": "return",
            "payload": {
                "aircraft_id": self.aircraft_id
            }
        }
        print(json.dumps(event_data), file=sys.stderr)
        
        # Enter maintenance
        yield self.env.timeout(self.maintenance_time)
        
        # Log maintenance end event
        event_data = {
            "time": self.env.now,
            "entity": "aircraft",
            "event": "maintenance_end",
            "payload": {
                "aircraft_id": self.aircraft_id
            }
        }
        print(json.dumps(event_data), file=sys.stderr)
        
        # Aircraft is now idle again
        self.is_busy = False
        self.current_pallet = None
        self.pallet_generation_time = None


def main():
    """Main simulation function."""
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
    queue = LoadingQueue(env)
    
    # Create facility
    facility = Facility(env, queue, args.pallet_interval)
    env.process(facility.generate_pallets())
    
    # Create aircraft
    aircraft_list = []
    for i in range(args.num_aircraft):
        aircraft = Aircraft(env, i+1, args.flight_time, args.unload_time, 
                           args.return_time, args.maintenance_time)
        aircraft_list.append(aircraft)
    
    # Create coordinator
    coordinator = FleetCoordinator(env, queue, aircraft_list)
    env.process(coordinator.assign_cargo())
    
    # Run simulation with periodic expiration checks
    while env.now < args.duration:
        # Check for expired pallets every second
        if env.now % 1 == 0:
            queue.check_expiration()
        env.step()
    
    # Print final statistics
    print(json.dumps({
        "time": args.duration,
        "entity": "simulation",
        "event": "completed",
        "payload": {
            "total_delivered": DELIVERED_PALLETS,
            "total_expired": TOTAL_EXPIRED
        }
    }))


if __name__ == "__main__":
    main()