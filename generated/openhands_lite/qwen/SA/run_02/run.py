#!/usr/bin/env python3
"""
Airfreight Logistics Operations Simulation
"""

import argparse
import json
import sys
from collections import deque
import simpy


# Global variables for simulation
env = None
facility = None
queue = None
coordinator = None
aircrafts = []
destination = None

# Event tracking
total_expired = 0
delivery_count = 0

# Simulation parameters
args = None


class Facility:
    """Generates new cargo pallets at regular intervals."""
    
    def __init__(self, env, queue, pallet_interval, pallet_expiration_time):
        self.env = env
        self.queue = queue
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.pallet_id_counter = 0
        self.pallet_generation_times = {}  # Track when pallets were generated
        
    def run(self):
        """Generate pallets at regular intervals."""
        while True:
            # Generate new pallet
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
            print(json.dumps(event_data))
            sys.stderr.flush()
            
            # Add pallet to queue
            self.queue.add_pallet(pallet_id, expiration_time)
            
            # Wait for next pallet generation
            yield self.env.timeout(self.pallet_interval)


class LoadingQueue:
    """Holds incoming pallets awaiting aircraft assignment."""
    
    def __init__(self, env):
        self.env = env
        self.pallets = deque()  # FIFO queue
        self.expiration_events = {}  # Track expiration events
        
    def add_pallet(self, pallet_id, expiration_time):
        """Add a pallet to the queue."""
        self.pallets.append((pallet_id, expiration_time))
        
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
        sys.stderr.flush()
        
        # Schedule expiration event
        expiration_event = self.env.process(self._handle_expiration(pallet_id, expiration_time))
        self.expiration_events[pallet_id] = expiration_event
        
    def get_pallet(self):
        """Get the next pallet from the queue (FIFO)."""
        if self.pallets:
            pallet_id, expiration_time = self.pallets.popleft()
            # Cancel expiration event
            if pallet_id in self.expiration_events:
                self.expiration_events[pallet_id].interrupt()
                del self.expiration_events[pallet_id]
            return pallet_id
        return None
        
    def get_queue_size(self):
        """Get current queue size."""
        return len(self.pallets)
        
    def _handle_expiration(self, pallet_id, expiration_time):
        """Handle pallet expiration."""
        try:
            # Wait until expiration time
            yield self.env.timeout(expiration_time - self.env.now)
        except simpy.Interrupt:
            # Expiration was cancelled (pallet was assigned)
            return
            
        # Check if pallet is still in queue (should be)
        # Remove from queue if still there
        pallets_list = list(self.pallets)
        if any(pallet[0] == pallet_id for pallet in pallets_list):
            self.pallets = deque([pallet for pallet in pallets_list if pallet[0] != pallet_id])
            
            # Log expiration
            global total_expired
            total_expired += 1
            event_data = {
                "time": self.env.now,
                "entity": "queue",
                "event": "pallet_expired",
                "payload": {
                    "pallet_id": pallet_id,
                    "total_expired": total_expired
                }
            }
            print(json.dumps(event_data))
            sys.stderr.flush()


class FleetCoordinator:
    """Monitors aircraft availability and cargo demand."""
    
    def __init__(self, env, queue, aircrafts):
        self.env = env
        self.queue = queue
        self.aircrafts = aircrafts
        
    def run(self):
        """Monitor and assign pallets to aircraft."""
        while True:
            # Check if there are pallets in queue and idle aircraft
            if self.queue.get_queue_size() > 0:
                idle_aircraft = [ac for ac in self.aircrafts if ac.is_idle()]
                if idle_aircraft:
                    # Assign next pallet to first idle aircraft
                    pallet_id = self.queue.get_pallet()
                    if pallet_id is not None:
                        aircraft = idle_aircraft[0]
                        aircraft.assign_pallet(pallet_id)
                        
                        # Log assignment
                        event_data = {
                            "time": self.env.now,
                            "entity": "coordinator",
                            "event": "assignment_created",
                            "payload": {
                                "aircraft_id": aircraft.aircraft_id,
                                "pallet_id": pallet_id
                            }
                        }
                        print(json.dumps(event_data))
                        sys.stderr.flush()
            
            # Wait a bit before next check
            yield self.env.timeout(0.1)


class Aircraft:
    """Represents an aircraft in the fleet."""
    
    def __init__(self, env, aircraft_id, flight_time, unload_time, return_time, maintenance_time, pallet_generation_times):
        self.env = env
        self.aircraft_id = aircraft_id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.state = "idle"  # idle, loading, flying, unloading, returning, maintenance
        self.current_pallet = None
        self.pallet_generation_times = pallet_generation_times  # Track when pallets were generated
        
    def is_idle(self):
        """Check if aircraft is idle."""
        return self.state == "idle"
        
    def assign_pallet(self, pallet_id):
        """Assign a pallet to this aircraft."""
        self.state = "loading"
        self.current_pallet = pallet_id
        
        # Log departure (instantaneous loading)
        event_data = {
            "time": self.env.now,
            "entity": "aircraft",
            "event": "depart",
            "payload": {
                "aircraft_id": self.aircraft_id,
                "pallet_id": pallet_id
            }
        }
        print(json.dumps(event_data))
        sys.stderr.flush()
        
        # Start the transport cycle
        self.env.process(self._transport_cycle(pallet_id))
        
    def _transport_cycle(self, pallet_id):
        """Execute the complete transport cycle."""
        # Loading is instantaneous (0s)
        # Fly to destination
        self.state = "flying"
        yield self.env.timeout(self.flight_time)
        
        # Unload at destination
        self.state = "unloading"
        yield self.env.timeout(self.unload_time)
        
        # Log delivery
        global delivery_count
        delivery_count += 1
        # Calculate latency
        latency = self.env.now - self.pallet_generation_times[pallet_id]
        event_data = {
            "time": self.env.now,
            "entity": "destination",
            "event": "pallet_delivered",
            "payload": {
                "pallet_id": pallet_id,
                "aircraft_id": self.aircraft_id,
                "latency": latency
            }
        }
        print(json.dumps(event_data))
        sys.stderr.flush()
        
        # Return to facility
        self.state = "returning"
        yield self.env.timeout(self.return_time)
        
        # Maintenance
        self.state = "maintenance"
        yield self.env.timeout(self.maintenance_time)
        
        # Return to idle
        self.state = "idle"
        self.current_pallet = None
        
        # Log return
        event_data = {
            "time": self.env.now,
            "entity": "aircraft",
            "event": "return",
            "payload": {
                "aircraft_id": self.aircraft_id
            }
        }
        print(json.dumps(event_data))
        sys.stderr.flush()


class Destination:
    """Logically receives delivered cargo."""
    
    def __init__(self, env):
        self.env = env
        self.deliveries = 0
        
    def record_delivery(self, pallet_id, aircraft_id, latency):
        """Record a successful delivery."""
        self.deliveries += 1
        event_data = {
            "time": self.env.now,
            "entity": "destination",
            "event": "pallet_delivered",
            "payload": {
                "pallet_id": pallet_id,
                "aircraft_id": aircraft_id,
                "latency": latency
            }
        }
        print(json.dumps(event_data))
        sys.stderr.flush()


def main():
    """Main simulation function."""
    global args, env, facility, queue, coordinator, aircrafts, destination
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Airfreight Logistics Operations Simulation')
    parser.add_argument('--duration', type=float, default=10000.0, help='Total simulation time in time units')
    parser.add_argument('--num_aircraft', type=int, default=2, help='Number of aircraft in the system')
    parser.add_argument('--pallet_interval', type=float, default=25.0, help='Time interval between pallet generations')
    parser.add_argument('--pallet_expiration_time', type=float, default=150.0, help='Time window for pallet expiration')
    parser.add_argument('--flight_time', type=float, default=30.0, help='Flight duration for aircraft transport')
    parser.add_argument('--unload_time', type=float, default=2.0, help='Time required for unloading cargo')
    parser.add_argument('--return_time', type=float, default=30.0, help='Return flight duration for aircraft')
    parser.add_argument('--maintenance_time', type=float, default=10.0, help='Duration of maintenance phase')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create system components
    queue = LoadingQueue(env)
    facility = Facility(env, queue, args.pallet_interval, args.pallet_expiration_time)
    destination = Destination(env)
    
    # Create aircraft fleet
    aircrafts = []
    for i in range(args.num_aircraft):
        aircraft = Aircraft(env, i + 1, args.flight_time, args.unload_time, args.return_time, args.maintenance_time, facility.pallet_generation_times)
        aircrafts.append(aircraft)
        
    # Create coordinator
    coordinator = FleetCoordinator(env, queue, aircrafts)
    
    # Start all processes
    env.process(facility.run())
    env.process(coordinator.run())
    
    # Run simulation
    env.run(until=args.duration)
    
    # Print final statistics
    print(json.dumps({
        "time": args.duration,
        "entity": "system",
        "event": "simulation_complete",
        "payload": {
            "total_deliveries": delivery_count,
            "total_expired": total_expired
        }
    }))


if __name__ == "__main__":
    main()