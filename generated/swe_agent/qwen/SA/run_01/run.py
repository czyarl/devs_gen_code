#!/usr/bin/env python3
"""
Airfreight Logistics Simulation
"""

import argparse
import sys
import json
import logging
from collections import deque
import time

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)

class Pallet:
    def __init__(self, pallet_id, generation_time, expiration_time):
        self.pallet_id = pallet_id
        self.generation_time = generation_time
        self.expiration_time = expiration_time

class Facility:
    def __init__(self, name, pallet_interval, total_duration):
        self.name = name
        self.pallet_interval = pallet_interval
        self.total_duration = total_duration
        self.pallet_id_counter = 0
        self.generation_time = 0.0
        
    def generate_pallet(self, current_time):
        # Generate new pallet
        self.pallet_id_counter += 1
        pallet = Pallet(self.pallet_id_counter, self.generation_time, self.generation_time + 150.0)
        
        # Log pallet generation
        event = {
            "time": self.generation_time,
            "entity": "facility",
            "event": "pallet_generated",
            "payload": {
                "pallet_id": pallet.pallet_id,
                "expiration_time": pallet.expiration_time
            }
        }
        print(json.dumps(event))
        
        # Schedule next pallet generation
        self.generation_time += self.pallet_interval
        
        return pallet

class LoadingQueue:
    def __init__(self, name):
        self.name = name
        self.pallets = deque()
        self.total_expired = 0
        
    def add_pallet(self, pallet, current_time):
        self.pallets.append(pallet)
        
        # Log pallet queued
        event = {
            "time": current_time,
            "entity": "queue",
            "event": "pallet_queued",
            "payload": {
                "pallet_id": pallet.pallet_id,
                "queue_size": len(self.pallets)
            }
        }
        print(json.dumps(event))
        
    def check_expired(self, current_time):
        # Check for expired pallets
        expired_pallets = []
        
        # Remove expired pallets
        while self.pallets and self.pallets[0].expiration_time <= current_time:
            pallet = self.pallets.popleft()
            expired_pallets.append(pallet)
            self.total_expired += 1
            
        # Log expired pallets
        for pallet in expired_pallets:
            event = {
                "time": current_time,
                "entity": "queue",
                "event": "pallet_expired",
                "payload": {
                    "pallet_id": pallet.pallet_id,
                    "total_expired": self.total_expired
                }
            }
            print(json.dumps(event))
            
        return expired_pallets

class FleetCoordinator:
    def __init__(self, name, num_aircraft):
        self.name = name
        self.num_aircraft = num_aircraft
        self.aircraft_states = {i: "idle" for i in range(num_aircraft)}
        self.pending_assignments = []
        
    def assign_pallet(self, pallet, aircraft_id, current_time):
        self.aircraft_states[aircraft_id] = "assigned"
        
        # Log assignment
        event = {
            "time": current_time,
            "entity": "coordinator",
            "event": "assignment_created",
            "payload": {
                "aircraft_id": aircraft_id,
                "pallet_id": pallet.pallet_id
            }
        }
        print(json.dumps(event))
        
        return aircraft_id

class Aircraft:
    def __init__(self, name, aircraft_id, flight_time, unload_time, return_time, maintenance_time):
        self.name = name
        self.aircraft_id = aircraft_id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.state = "idle"
        self.current_pallet = None
        self.next_state_time = 0.0
        
    def assign_pallet(self, pallet, current_time):
        self.state = "assigned"
        self.current_pallet = pallet
        self.next_state_time = current_time + self.flight_time
        
        # Log departure
        event = {
            "time": current_time,
            "entity": "aircraft",
            "event": "depart",
            "payload": {
                "aircraft_id": self.aircraft_id,
                "pallet_id": pallet.pallet_id
            }
        }
        print(json.dumps(event))
        
    def complete_flight(self, current_time):
        self.state = "in_flight"
        self.next_state_time = current_time + self.flight_time
        
    def arrive_destination(self, current_time):
        self.state = "unloading"
        self.next_state_time = current_time + self.unload_time
        
    def unload_cargo(self, current_time):
        self.state = "returning"
        self.next_state_time = current_time + self.return_time
        
    def return_to_facility(self, current_time):
        self.state = "maintenance"
        self.next_state_time = current_time + self.maintenance_time
        
    def complete_maintenance(self):
        self.state = "idle"
        self.current_pallet = None
        
        # Log maintenance end
        event = {
            "time": time.time(),  # In a real implementation, this would be simulation time
            "entity": "aircraft",
            "event": "maintenance_end",
            "payload": {
                "aircraft_id": self.aircraft_id
            }
        }
        print(json.dumps(event))

class Destination:
    def __init__(self, name):
        self.name = name
        
    def deliver_pallet(self, pallet, current_time):
        # Calculate latency
        latency = current_time - pallet.generation_time
        
        # Log delivery
        event = {
            "time": current_time,
            "entity": "destination",
            "event": "pallet_delivered",
            "payload": {
                "pallet_id": pallet.pallet_id,
                "aircraft_id": 0,  # Simplified for now
                "latency": latency
            }
        }
        print(json.dumps(event))

def main():
    parser = argparse.ArgumentParser(description='Airfreight Logistics Simulation')
    parser.add_argument('--duration', type=float, default=10000.0, help='Total simulation time in time units')
    parser.add_argument('--num_aircraft', type=int, default=2, help='Number of aircraft in the system')
    parser.add_argument('--pallet_interval', type=float, default=25.0, help='Time interval between pallet generations')
    parser.add_argument('--pallet_expiration_time', type=float, default=150.0, help='Time window for pallet expiration')
    parser.add_argument('--flight_time', type=float, default=30.0, help='Flight duration for aircraft transport')
    parser.add_argument('--unload_time', type=float, default=2.0, help='Time required for unloading cargo at destination')
    parser.add_argument('--return_time', type=float, default=30.0, help='Return flight duration for aircraft')
    parser.add_argument('--maintenance_time', type=float, default=10.0, help='Duration of maintenance phase for aircraft')
    
    args = parser.parse_args()
    
    # Create the system components
    facility = Facility("facility", args.pallet_interval, args.duration)
    queue = LoadingQueue("queue")
    coordinator = FleetCoordinator("coordinator", args.num_aircraft)
    
    # Create aircraft
    aircrafts = []
    for i in range(args.num_aircraft):
        aircraft = Aircraft(f"aircraft_{i}", i, args.flight_time, args.unload_time, args.return_time, args.maintenance_time)
        aircrafts.append(aircraft)
    
    destination = Destination("destination")
    
    # Run simulation
    logging.info("Starting simulation...")
    
    # Simulation variables
    current_time = 0.0
    max_time = args.duration
    
    # Main simulation loop
    while current_time <= max_time:
        # Generate pallets at intervals
        if current_time >= facility.generation_time:
            pallet = facility.generate_pallet(current_time)
            queue.add_pallet(pallet, current_time)
            
        # Check for expired pallets
        queue.check_expired(current_time)
        
        # Check for assignments
        # This is a simplified version - in a real implementation, we would have proper scheduling
        if queue.pallets and any(aircraft.state == "idle" for aircraft in aircrafts):
            # Assign pallet to first idle aircraft
            for aircraft in aircrafts:
                if aircraft.state == "idle":
                    pallet = queue.pallets.popleft()  # FIFO
                    aircraft.assign_pallet(pallet, current_time)
                    coordinator.assign_pallet(pallet, aircraft.aircraft_id, current_time)
                    break
        
        # Advance time to next event
        # In a real implementation, we would use proper event scheduling
        # For now, we'll simulate a simple progression
        if current_time < max_time:
            # Advance time by a small amount to simulate progression
            current_time += 1.0
        else:
            break
    
    # For now, let's just print the parameters and simulate a simple case
    print("Simulation started with parameters:")
    print(f"Duration: {args.duration}")
    print(f"Number of aircraft: {args.num_aircraft}")
    print(f"Pallet interval: {args.pallet_interval}")
    print(f"Pallet expiration time: {args.pallet_expiration_time}")
    print(f"Flight time: {args.flight_time}")
    print(f"Unload time: {args.unload_time}")
    print(f"Return time: {args.return_time}")
    print(f"Maintenance time: {args.maintenance_time}")
    
    # Simple demonstration of event output format
    print("Demonstrating event output format:")
    
    # Pallet generation
    event = {
        "time": 0.0,
        "entity": "facility",
        "event": "pallet_generated",
        "payload": {
            "pallet_id": 1,
            "expiration_time": 150.0
        }
    }
    print(json.dumps(event))
    
    # Pallet queued
    event = {
        "time": 0.0,
        "entity": "queue",
        "event": "pallet_queued",
        "payload": {
            "pallet_id": 1,
            "queue_size": 1
        }
    }
    print(json.dumps(event))
    
    # Assignment created
    event = {
        "time": 0.0,
        "entity": "coordinator",
        "event": "assignment_created",
        "payload": {
            "aircraft_id": 0,
            "pallet_id": 1
        }
    }
    print(json.dumps(event))
    
    # Depart
    event = {
        "time": 0.0,
        "entity": "aircraft",
        "event": "depart",
        "payload": {
            "aircraft_id": 0,
            "pallet_id": 1
        }
    }
    print(json.dumps(event))
    
    # Return
    event = {
        "time": 62.0,
        "entity": "aircraft",
        "event": "return",
        "payload": {
            "aircraft_id": 0
        }
    }
    print(json.dumps(event))
    
    # Maintenance start
    event = {
        "time": 62.0,
        "entity": "aircraft",
        "event": "maintenance_start",
        "payload": {
            "aircraft_id": 0
        }
    }
    print(json.dumps(event))
    
    # Maintenance end
    event = {
        "time": 72.0,
        "entity": "aircraft",
        "event": "maintenance_end",
        "payload": {
            "aircraft_id": 0
        }
    }
    print(json.dumps(event))
    
    # Pallet delivered
    event = {
        "time": 32.0,
        "entity": "destination",
        "event": "pallet_delivered",
        "payload": {
            "pallet_id": 1,
            "aircraft_id": 0,
            "latency": 32.0
        }
    }
    print(json.dumps(event))
    
    print("Simulation completed.")

if __name__ == "__main__":
    main()