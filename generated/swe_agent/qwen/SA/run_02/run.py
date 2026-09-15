#!/usr/bin/env python3
"""
Airfreight Logistics Simulation using xdevs
"""

import argparse
import sys
import json
import logging
from collections import deque
import random
import xdevs.models

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)

class Pallet:
    def __init__(self, pallet_id, generation_time, expiration_time):
        self.pallet_id = pallet_id
        self.generation_time = generation_time
        self.expiration_time = expiration_time

class Facility(xdevs.models.Atomic):
    def __init__(self, name, pallet_interval, total_duration):
        super().__init__(name)
        self.pallet_interval = pallet_interval
        self.total_duration = total_duration
        self.pallet_id_counter = 0
        self.generation_time = 0.0
        self.next_pallet_time = 0.0
        
        # Create output port
        self.o_out = xdevs.models.Port(dict, "o_out")
        self.add_out_port(self.o_out)
        
    def initialize(self):
        self.pallet_id_counter = 0
        self.generation_time = 0.0
        self.next_pallet_time = 0.0
        return self.pallet_interval
    
    def exit(self):
        pass
    
    def deltext(self, e):
        pass
    
    def deltint(self):
        # Generate new pallet
        self.pallet_id_counter += 1
        self.generation_time = self.sigma
        self.next_pallet_time = self.sigma + self.pallet_interval
        
        # Create pallet with expiration time
        expiration_time = self.sigma + 150.0  # Default expiration time
        
        pallet = Pallet(self.pallet_id_counter, self.generation_time, expiration_time)
        
        # Log pallet generation
        event = {
            "time": self.sigma,
            "entity": "facility",
            "event": "pallet_generated",
            "payload": {
                "pallet_id": pallet.pallet_id,
                "expiration_time": pallet.expiration_time
            }
        }
        print(json.dumps(event))
        
        # Schedule next pallet generation
        return self.pallet_interval
    
    def lambdaf(self):
        # Output the pallet to the queue
        self.o_out.add({"pallet": {"pallet_id": self.pallet_id_counter, "generation_time": self.generation_time, "expiration_time": self.generation_time + 150.0}})
    
    def ta(self):
        # Return time until next pallet generation
        return self.pallet_interval

class LoadingQueue(xdevs.models.Atomic):
    def __init__(self, name):
        super().__init__(name)
        self.queue = deque()
        self.total_expired = 0
        
        # Create input and output ports
        self.i_in = xdevs.models.Port(dict, "i_in")
        self.o_out = xdevs.models.Port(dict, "o_out")
        self.add_in_port(self.i_in)
        self.add_out_port(self.o_out)
        
    def initialize(self):
        self.queue = deque()
        self.total_expired = 0
        return float('inf')
    
    def exit(self):
        pass
    
    def deltext(self, e):
        # Get data from input port
        if self.i_in:
            data = self.i_in.get()
            if "pallet" in data:
                pallet = data["pallet"]
                self.queue.append(pallet)
                
                # Log pallet queued
                event = {
                    "time": self.sigma,
                    "entity": "queue",
                    "event": "pallet_queued",
                    "payload": {
                        "pallet_id": pallet["pallet_id"],
                        "queue_size": len(self.queue)
                    }
                }
                print(json.dumps(event))
    
    def deltint(self):
        # Check for expired pallets
        expired_pallets = []
        for pallet in list(self.queue):
            if self.sigma >= pallet["expiration_time"]:
                expired_pallets.append(pallet)
        
        # Remove expired pallets
        for pallet in expired_pallets:
            self.queue.remove(pallet)
            self.total_expired += 1
            
            # Log pallet expired
            event = {
                "time": self.sigma,
                "entity": "queue",
                "event": "pallet_expired",
                "payload": {
                    "pallet_id": pallet["pallet_id"],
                    "total_expired": self.total_expired
                }
            }
            print(json.dumps(event))
        
        return 0.0
    
    def lambdaf(self):
        # Output the next pallet if available
        if self.queue:
            pallet = self.queue[0]
            self.o_out.add({"pallet": pallet})
        else:
            self.o_out.add({})
    
    def ta(self):
        # Return time until next check (or infinity if no items)
        if self.queue:
            # Check for expiration
            earliest_expiration = min(pallet["expiration_time"] for pallet in self.queue)
            return earliest_expiration - self.sigma
        return float('inf')

class FleetCoordinator(xdevs.models.Atomic):
    def __init__(self, name, num_aircraft):
        super().__init__(name)
        self.num_aircraft = num_aircraft
        self.aircraft_states = {i: "idle" for i in range(num_aircraft)}
        self.pending_assignments = []
        
        # Create input and output ports
        self.i_in = xdevs.models.Port(dict, "i_in")
        self.o_out = xdevs.models.Port(dict, "o_out")
        self.add_in_port(self.i_in)
        self.add_out_port(self.o_out)
        
    def initialize(self):
        self.aircraft_states = {i: "idle" for i in range(self.num_aircraft)}
        self.pending_assignments = []
        return float('inf')
    
    def exit(self):
        pass
    
    def deltext(self, e):
        # Get data from input port
        if self.i_in:
            data = self.i_in.get()
            # Handle aircraft status updates
            if "aircraft_status" in data:
                aircraft_id = data["aircraft_status"]["aircraft_id"]
                status = data["aircraft_status"]["status"]
                self.aircraft_states[aircraft_id] = status
                
                # Check if we can assign a pallet
                if status == "idle" and self.pending_assignments:
                    # Assign the next pallet
                    pallet = self.pending_assignments.pop(0)
                    self.aircraft_states[aircraft_id] = "assigned"
                    
                    # Log assignment
                    event = {
                        "time": self.sigma,
                        "entity": "coordinator",
                        "event": "assignment_created",
                        "payload": {
                            "aircraft_id": aircraft_id,
                            "pallet_id": pallet["pallet_id"]
                        }
                    }
                    print(json.dumps(event))
                    
                    self.o_out.add({"assignment": {"aircraft_id": aircraft_id, "pallet": pallet}})
                    return self.flight_time + self.unload_time + self.return_time + self.maintenance_time
        return {}
    
    def deltint(self):
        return 0.0
    
    def lambdaf(self):
        pass
    
    def ta(self):
        return float('inf')

class Aircraft(xdevs.models.Atomic):
    def __init__(self, name, aircraft_id, flight_time, unload_time, return_time, maintenance_time):
        super().__init__(name)
        self.aircraft_id = aircraft_id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.state = "idle"
        self.current_pallet = None
        self.departure_time = 0.0
        
        # Create input and output ports
        self.i_in = xdevs.models.Port(dict, "i_in")
        self.o_out = xdevs.models.Port(dict, "o_out")
        self.add_in_port(self.i_in)
        self.add_out_port(self.o_out)
        
    def initialize(self):
        self.state = "idle"
        self.current_pallet = None
        self.departure_time = 0.0
        return float('inf')
    
    def exit(self):
        pass
    
    def deltext(self, e):
        # Get data from input port
        if self.i_in:
            data = self.i_in.get()
            if "assignment" in data:
                assignment = data["assignment"]
                self.current_pallet = assignment["pallet"]
                self.state = "assigned"
                self.departure_time = self.sigma
                
                # Log departure
                event = {
                    "time": self.sigma,
                    "entity": "aircraft",
                    "event": "depart",
                    "payload": {
                        "aircraft_id": self.aircraft_id,
                        "pallet_id": self.current_pallet["pallet_id"]
                    }
                }
                print(json.dumps(event))
                
                # Schedule return
                return self.flight_time + self.unload_time + self.return_time + self.maintenance_time
                
            elif "aircraft_status" in data:
                # Handle status updates from coordinator
                pass
                
        return 0.0
    
    def deltint(self):
        # Handle state transitions
        if self.state == "assigned":
            # Aircraft is assigned, now it's flying
            self.state = "flying"
            return self.flight_time
        elif self.state == "flying":
            # Aircraft has arrived at destination
            self.state = "unloading"
            return self.unload_time
        elif self.state == "unloading":
            # Aircraft is unloading
            self.state = "returning"
            return self.return_time
        elif self.state == "returning":
            # Aircraft is returning
            self.state = "maintenance"
            return self.maintenance_time
        elif self.state == "maintenance":
            # Maintenance complete, back to idle
            self.state = "idle"
            self.current_pallet = None
            
            # Log maintenance end
            event = {
                "time": self.sigma,
                "entity": "aircraft",
                "event": "maintenance_end",
                "payload": {
                    "aircraft_id": self.aircraft_id
                }
            }
            print(json.dumps(event))
            
            # Log delivery
            event = {
                "time": self.sigma,
                "entity": "destination",
                "event": "pallet_delivered",
                "payload": {
                    "pallet_id": self.current_pallet["pallet_id"],
                    "aircraft_id": self.aircraft_id,
                    "latency": self.sigma - self.current_pallet["generation_time"]
                }
            }
            print(json.dumps(event))
            
            return 0.0
        return 0.0
    
    def lambdaf(self):
        # Output status updates
        if self.state == "idle":
            self.o_out.add({"aircraft_status": {"aircraft_id": self.aircraft_id, "status": "idle"}})
        elif self.state == "maintenance":
            self.o_out.add({"aircraft_status": {"aircraft_id": self.aircraft_id, "status": "maintenance"}})
        else:
            self.o_out.add({})
    
    def ta(self):
        # Return time until next state transition
        if self.state == "idle":
            return float('inf')
        elif self.state == "assigned":
            return self.flight_time + self.unload_time + self.return_time + self.maintenance_time
        elif self.state == "flying":
            return self.flight_time
        elif self.state == "unloading":
            return self.unload_time
        elif self.state == "returning":
            return self.return_time
        elif self.state == "maintenance":
            return self.maintenance_time
        return 0.0

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
    
    # Create the system model
    facility = Facility("facility", args.pallet_interval, args.duration)
    queue = LoadingQueue("queue")
    coordinator = FleetCoordinator("coordinator", args.num_aircraft)
    
    # Create aircraft models
    aircrafts = []
    for i in range(args.num_aircraft):
        aircraft = Aircraft(f"aircraft_{i}", i, args.flight_time, args.unload_time, args.return_time, args.maintenance_time)
        aircrafts.append(aircraft)
    
    # Create the system
    system = xdevs.models.Coupled("airfreight_system")
    system.add_component(facility)
    system.add_component(queue)
    system.add_component(coordinator)
    for aircraft in aircrafts:
        system.add_component(aircraft)
    
    # Add couplings
    # Facility to queue
    system.add_coupling(facility.o_out, queue.i_in)
    
    # Queue to coordinator
    system.add_coupling(queue.o_out, coordinator.i_in)
    
    # Coordinator to aircraft
    for i, aircraft in enumerate(aircrafts):
        system.add_coupling(coordinator.o_out, aircraft.i_in)
    
    # Aircraft to coordinator
    for i, aircraft in enumerate(aircrafts):
        system.add_coupling(aircraft.o_out, coordinator.i_in)
    
    # Create coordinator and run simulation
    from xdevs.sim import Coordinator
    coord = Coordinator(system)
    coord.initialize()
    
    # Run the simulation
    coord.simulate(args.duration)
    
    # Print final statistics
    logging.info("Simulation completed")

if __name__ == "__main__":
    main()