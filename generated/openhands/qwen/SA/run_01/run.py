#!/usr/bin/env python3
"""
Airfreight Logistics Operations Simulation
"""

import argparse
import sys
import json
import logging
from collections import deque
import simpy


class Facility:
    """Generates new cargo pallets at regular intervals."""
    
    def __init__(self, env, queue, pallet_interval, pallet_expiration_time):
        self.env = env
        self.queue = queue
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.pallet_id_counter = 0
        self.pallets_data = {}  # Store pallet generation times
        self.process = env.process(self._generate_pallets())
        
    def _generate_pallets(self):
        """Generate pallets at regular intervals."""
        while True:
            # Generate new pallet
            self.pallet_id_counter += 1
            pallet_id = self.pallet_id_counter
            expiration_time = self.env.now + self.pallet_expiration_time
            generation_time = self.env.now
            
            # Store pallet data
            self.pallets_data[pallet_id] = generation_time
            
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
            
            # Add to queue
            self.queue.put(pallet_id, expiration_time, generation_time)
            
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
    """Holds incoming pallets awaiting aircraft assignment."""
    
    def __init__(self, env):
        self.env = env
        self.pallets = deque()  # (pallet_id, expiration_time, generation_time)
        self.expired_count = 0
        
    def put(self, pallet_id, expiration_time, generation_time):
        """Add a pallet to the queue."""
        self.pallets.append((pallet_id, expiration_time, generation_time))
        
    def get(self):
        """Get the next pallet from the queue (FIFO)."""
        if self.pallets:
            return self.pallets.popleft()
        return None
        
    def check_expiration(self):
        """Check for expired pallets and remove them."""
        expired = []
        current_time = self.env.now
        
        # Check all pallets in queue
        # We need to iterate through the queue and remove expired items
        # Since deque doesn't support popping by index, we'll rebuild the queue
        temp_pallets = deque()
        
        while self.pallets:
            pallet_id, expiration_time, generation_time = self.pallets.popleft()
            if current_time >= expiration_time:
                # This pallet has expired
                expired.append((pallet_id, generation_time))
                self.expired_count += 1
            else:
                # Keep this pallet
                temp_pallets.append((pallet_id, expiration_time, generation_time))
                
        # Put the non-expired pallets back
        self.pallets = temp_pallets
        
        # Log expired pallets
        for pallet_id, _ in expired:
            event_data = {
                "time": current_time,
                "entity": "queue",
                "event": "pallet_expired",
                "payload": {
                    "pallet_id": pallet_id,
                    "total_expired": self.expired_count
                }
            }
            print(json.dumps(event_data), file=sys.stdout)
            
        return len(expired) > 0


class FleetCoordinator:
    """Manages aircraft availability and cargo assignment."""
    
    def __init__(self, env, queue, aircraft_list):
        self.env = env
        self.queue = queue
        self.aircraft_list = aircraft_list
        self.process = env.process(self._monitor_assignments())
        
    def _monitor_assignments(self):
        """Monitor queue and aircraft availability to assign cargo."""
        while True:
            # Check for expired pallets first
            self.queue.check_expiration()
            
            # Check if there are pallets in queue and aircraft available
            if self.queue.pallets and any(not aircraft.is_busy for aircraft in self.aircraft_list):
                # Get next pallet from queue
                pallet_id, _, generation_time = self.queue.get()
                
                # Find an idle aircraft
                assigned_aircraft = None
                for aircraft in self.aircraft_list:
                    if not aircraft.is_busy:
                        assigned_aircraft = aircraft
                        break
                        
                if assigned_aircraft:
                    # Assign pallet to aircraft
                    assigned_aircraft.assign_pallet(pallet_id, generation_time)
                    
                    # Log assignment
                    event_data = {
                        "time": self.env.now,
                        "entity": "coordinator",
                        "event": "assignment_created",
                        "payload": {
                            "aircraft_id": assigned_aircraft.id,
                            "pallet_id": pallet_id
                        }
                    }
                    print(json.dumps(event_data), file=sys.stdout)
                    
            yield self.env.timeout(0.1)  # Small delay to avoid busy waiting


class Aircraft:
    """Represents an aircraft in the fleet."""
    
    def __init__(self, env, id, flight_time, unload_time, return_time, maintenance_time):
        self.env = env
        self.id = id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.is_busy = False
        self.current_pallet_id = None
        self.process = env.process(self._operate())
        
    def assign_pallet(self, pallet_id, generation_time):
        """Assign a pallet to this aircraft."""
        self.is_busy = True
        self.current_pallet_id = pallet_id
        self.generation_time = generation_time
        
    def _operate(self):
        """Main operating cycle of the aircraft."""
        while True:
            if not self.is_busy:
                # Wait for assignment
                yield self.env.timeout(1)
                continue
                
            # Load (instantaneous)
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
                    "latency": self.env.now - self.generation_time
                }
            }
            print(json.dumps(event_data), file=sys.stdout)
            
            # Return to facility
            event_data = {
                "time": self.env.now,
                "entity": "aircraft",
                "event": "return",
                "payload": {
                    "aircraft_id": self.id
                }
            }
            print(json.dumps(event_data), file=sys.stdout)
            
            yield self.env.timeout(self.return_time)
            
            # Maintenance
            event_data = {
                "time": self.env.now,
                "entity": "aircraft",
                "event": "maintenance_start",
                "payload": {
                    "aircraft_id": self.id
                }
            }
            print(json.dumps(event_data), file=sys.stdout)
            
            yield self.env.timeout(self.maintenance_time)
            
            # Maintenance end
            event_data = {
                "time": self.env.now,
                "entity": "aircraft",
                "event": "maintenance_end",
                "payload": {
                    "aircraft_id": self.id
                }
            }
            print(json.dumps(event_data), file=sys.stdout)
            
            # Aircraft is now idle
            self.is_busy = False
            self.current_pallet_id = None


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
    
    # Create system components
    queue = LoadingQueue(env)
    facility = Facility(env, queue, args.pallet_interval, args.pallet_expiration_time)
    
    # Create aircraft
    aircraft_list = []
    for i in range(args.num_aircraft):
        aircraft = Aircraft(env, i + 1, args.flight_time, args.unload_time, args.return_time, args.maintenance_time)
        aircraft_list.append(aircraft)
    
    # Create coordinator
    coordinator = FleetCoordinator(env, queue, aircraft_list)
    
    # Run simulation
    env.run(until=args.duration)
    
    # Print final status
    print(json.dumps({
        "time": args.duration,
        "entity": "system",
        "event": "simulation_end",
        "payload": {
            "duration": args.duration
        }
    }), file=sys.stdout)


if __name__ == "__main__":
    main()