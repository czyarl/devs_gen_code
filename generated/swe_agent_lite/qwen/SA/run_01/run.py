#!/usr/bin/env python3
"""
Airfreight Logistics Operations Simulation
"""

import argparse
import sys
import json
import logging
import random
from collections import deque
import time

# For discrete event simulation
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
        self.pallet_generation_times = {}  # Store generation times for latency calculation
        self.process = env.process(self._generate_pallets())
        
    def _generate_pallets(self):
        """Generate pallets at regular intervals"""
        while True:
            # Generate a new pallet
            self.pallet_id_counter += 1
            pallet_id = self.pallet_id_counter
            expiration_time = self.env.now + self.pallet_expiration_time
            self.pallet_generation_times[pallet_id] = self.env.now
            
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
            print(json.dumps(event_data), file=sys.stdout)
            
            # Add pallet to queue
            self.queue.add_pallet(pallet_id, expiration_time)
            
            # Log pallet queued
            event_data = {
                "time": self.env.now,
                "entity": "queue",
                "event": "pallet_queued",
                "payload": {
                    "pallet_id": pallet_id,
                    "queue_size": len(self.queue.pallets)
                }
            }
            print(json.dumps(event_data), file=sys.stdout)
            
            # Wait for next pallet generation
            yield self.env.timeout(self.pallet_interval)

class LoadingQueue:
    """Holds incoming pallets awaiting aircraft assignment"""
    
    def __init__(self, env):
        self.env = env
        self.pallets = deque()  # Store pallets as (pallet_id, expiration_time)
        self.total_expired = 0
        
    def add_pallet(self, pallet_id, expiration_time):
        """Add a pallet to the queue"""
        self.pallets.append((pallet_id, expiration_time))
        
    def get_next_pallet(self):
        """Get the next pallet from the queue (FIFO)"""
        if self.pallets:
            return self.pallets.popleft()
        return None
        
    def check_expired_pallets(self):
        """Check for expired pallets and remove them"""
        expired_count = 0
        # Create a new list without expired pallets
        new_pallets = deque()
        
        for pallet_id, expiration_time in self.pallets:
            if self.env.now >= expiration_time:
                # Pallet expired
                self.total_expired += 1
                expired_count += 1
                event_data = {
                    "time": self.env.now,
                    "entity": "queue",
                    "event": "pallet_expired",
                    "payload": {
                        "pallet_id": pallet_id,
                        "total_expired": self.total_expired
                    }
                }
                print(json.dumps(event_data), file=sys.stdout)
            else:
                # Pallet still valid
                new_pallets.append((pallet_id, expiration_time))
                
        self.pallets = new_pallets
        return expired_count

class FleetCoordinator:
    """Monitors aircraft availability and cargo demand"""
    
    def __init__(self, env, queue, aircraft_list):
        self.env = env
        self.queue = queue
        self.aircraft_list = aircraft_list
        self.process = env.process(self._monitor_assignments())
        
    def _monitor_assignments(self):
        """Monitor for assignments"""
        while True:
            # Check if there are pallets in queue and aircraft available
            if self.queue.pallets and any(aircraft.is_idle() for aircraft in self.aircraft_list):
                # Get next pallet from queue
                pallet_data = self.queue.get_next_pallet()
                if pallet_data:
                    pallet_id, _ = pallet_data
                    
                    # Find an idle aircraft
                    idle_aircraft = None
                    for aircraft in self.aircraft_list:
                        if aircraft.is_idle():
                            idle_aircraft = aircraft
                            break
                    
                    if idle_aircraft:
                        # Assign pallet to aircraft
                        idle_aircraft.assign_pallet(pallet_id)
                        
                        event_data = {
                            "time": self.env.now,
                            "entity": "coordinator",
                            "event": "assignment_created",
                            "payload": {
                                "aircraft_id": idle_aircraft.id,
                                "pallet_id": pallet_id
                            }
                        }
                        print(json.dumps(event_data), file=sys.stdout)
                        
            yield self.env.timeout(0.1)  # Check periodically

class Aircraft:
    """Represents an aircraft in the fleet"""
    
    def __init__(self, env, id, flight_time, unload_time, return_time, maintenance_time):
        self.env = env
        self.id = id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.state = "idle"  # idle, loading, flying, unloading, returning, maintenance
        self.current_pallet_id = None
        self.pallet_generation_times = {}  # Store generation times for latency calculation
        self.process = env.process(self._run_cycle())
        
    def is_idle(self):
        """Check if aircraft is idle"""
        return self.state == "idle"
        
    def assign_pallet(self, pallet_id):
        """Assign a pallet to this aircraft"""
        self.state = "loading"
        self.current_pallet_id = pallet_id
        
    def _run_cycle(self):
        """Run the aircraft cycle"""
        while True:
            if self.state == "idle":
                # Wait for assignment
                yield self.env.timeout(1)
            elif self.state == "loading":
                # Loading is instantaneous
                self.state = "flying"
                
                event_data = {
                    "time": self.env.now,
                    "entity": "aircraft",
                    "event": "depart",
                    "payload": {
                        "aircraft_id": self.id,
                        "pallet_id": self.current_pallet_id
                    }
                }
                print(json.dumps(event_data), file=sys.stdout)
                
                # Fly to destination
                yield self.env.timeout(self.flight_time)
                self.state = "unloading"
                
            elif self.state == "unloading":
                # Unload cargo
                yield self.env.timeout(self.unload_time)
                
                # Record delivery
                latency = self.env.now - self.pallet_generation_times[self.current_pallet_id]
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
                print(json.dumps(event_data), file=sys.stdout)
                
                self.state = "returning"
                
            elif self.state == "returning":
                # Return to facility
                yield self.env.timeout(self.return_time)
                
                event_data = {
                    "time": self.env.now,
                    "entity": "aircraft",
                    "event": "return",
                    "payload": {
                        "aircraft_id": self.id
                    }
                }
                print(json.dumps(event_data), file=sys.stdout)
                
                self.state = "maintenance"
                self.current_pallet_id = None
                
            elif self.state == "maintenance":
                # Maintenance phase
                yield self.env.timeout(self.maintenance_time)
                
                event_data = {
                    "time": self.env.now,
                    "entity": "aircraft",
                    "event": "maintenance_end",
                    "payload": {
                        "aircraft_id": self.id
                    }
                }
                print(json.dumps(event_data), file=sys.stdout)
                
                self.state = "idle"

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
    
    # Create entities
    queue = LoadingQueue(env)
    facility = Facility(env, queue, args.pallet_interval, args.pallet_expiration_time)
    
    # Create aircraft
    aircraft_list = []
    for i in range(args.num_aircraft):
        aircraft = Aircraft(env, i+1, args.flight_time, args.unload_time, args.return_time, args.maintenance_time)
        aircraft_list.append(aircraft)
    
    # Create coordinator
    coordinator = FleetCoordinator(env, queue, aircraft_list)
    
    # Run simulation
    start_time = time.time()
    try:
        # Run the simulation with periodic expiration checks
        while env.now < args.duration:
            # Check for expired pallets
            queue.check_expired_pallets()
            # Run one step of the simulation
            env.step()
    except KeyboardInterrupt:
        pass
    
    # Ensure simulation ends in 10 seconds real time
    elapsed_time = time.time() - start_time
    if elapsed_time < 10:
        time.sleep(10 - elapsed_time)

if __name__ == "__main__":
    main()