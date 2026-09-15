```python_code
import argparse
import sys
import json
import logging
import random
from collections import deque
import time

# Define simulation constants
DEFAULT_DURATION = 10000.0
DEFAULT_NUM_AIRCRAFT = 2
DEFAULT_PALLET_INTERVAL = 25.0
DEFAULT_PALLET_EXPIRATION_TIME = 150.0
DEFAULT_FLIGHT_TIME = 30.0
DEFAULT_UNLOAD_TIME = 2.0
DEFAULT_RETURN_TIME = 30.0
DEFAULT_MAINTENANCE_TIME = 10.0

class SimulationEvent:
    def __init__(self, time, entity, event, payload):
        self.time = time
        self.entity = entity
        self.event = event
        self.payload = payload

    def to_json(self):
        return json.dumps({
            "time": self.time,
            "entity": self.entity,
            "event": self.event,
            "payload": self.payload
        })

class Pallet:
    def __init__(self, pallet_id, expiration_time):
        self.pallet_id = pallet_id
        self.expiration_time = expiration_time

class Aircraft:
    def __init__(self, aircraft_id, flight_time, unload_time, return_time, maintenance_time):
        self.aircraft_id = aircraft_id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.state = "idle"  # idle, loading, flying, unloading, returning, maintenance
        self.current_pallet = None
        self.next_event_time = 0.0

class Facility:
    def __init__(self, env, queue, coordinator, pallet_interval, pallet_expiration_time):
        self.env = env
        self.queue = queue
        self.coordinator = coordinator
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.pallet_counter = 0
        self.pallets_generated = 0

    def generate_pallet(self):
        while True:
            yield self.env.timeout(self.pallet_interval)
            self.pallet_counter += 1
            expiration_time = self.env.now + self.pallet_expiration_time
            pallet = Pallet(self.pallet_counter, expiration_time)
            self.pallets_generated += 1
            # Log pallet generation
            event = SimulationEvent(
                self.env.now,
                "facility",
                "pallet_generated",
                {
                    "pallet_id": pallet.pallet_id,
                    "expiration_time": expiration_time
                }
            )
            print(event.to_json(), file=sys.stdout)
            
            # Add to queue
            self.queue.add_pallet(pallet)

class LoadingQueue:
    def __init__(self, env, coordinator):
        self.env = env
        self.coordinator = coordinator
        self.pallets = deque()
        self.total_expired = 0

    def add_pallet(self, pallet):
        self.pallets.append(pallet)
        # Log pallet queued
        event = SimulationEvent(
            self.env.now,
            "queue",
            "pallet_queued",
            {
                "pallet_id": pallet.pallet_id,
                "queue_size": len(self.pallets)
            }
        )
        print(event.to_json(), file=sys.stdout)
        
        # Check if we can assign to aircraft
        self.coordinator.check_assignment()

    def remove_pallet(self, pallet):
        self.pallets.remove(pallet)
        # Check if we can assign to aircraft
        self.coordinator.check_assignment()

    def check_expiration(self):
        # Check for expired pallets
        expired = []
        for pallet in list(self.pallets):
            if self.env.now >= pallet.expiration_time:
                expired.append(pallet)
        
        for pallet in expired:
            self.total_expired += 1
            self.remove_pallet(pallet)
            # Log pallet expired
            event = SimulationEvent(
                self.env.now,
                "queue",
                "pallet_expired",
                {
                    "pallet_id": pallet.pallet_id,
                    "total_expired": self.total_expired
                }
            )
            print(event.to_json(), file=sys.stdout)

class Coordinator:
    def __init__(self, env, queue, aircraft_list):
        self.env = env
        self.queue = queue
        self.aircraft_list = aircraft_list

    def check_assignment(self):
        # Check for available aircraft and pallets
        if len(self.queue.pallets) > 0:
            for aircraft in self.aircraft_list:
                if aircraft.state == "idle":
                    # Assign the next pallet
                    pallet = self.queue.pallets[0]
                    self.assign_pallet(aircraft, pallet)
                    return

    def assign_pallet(self, aircraft, pallet):
        aircraft.state = "loading"
        aircraft.current_pallet = pallet
        self.queue.remove_pallet(pallet)
        
        # Log assignment
        event = SimulationEvent(
            self.env.now,
            "coordinator",
            "assignment_created",
            {
                "aircraft_id": aircraft.aircraft_id,
                "pallet_id": pallet.pallet_id
            }
        )
        print(event.to_json(), file=sys.stdout)
        
        # Trigger aircraft to load
        self.env.process(aircraft_process(self.env, aircraft))

class AircraftProcess:
    def __init__(self, env, aircraft):
        self.env = env
        self.aircraft = aircraft

    def process(self):
        # Loading (0s)
        # Aircraft is ready to depart now
        self.aircraft.state = "flying"
        self.aircraft.next_event_time = self.env.now + self.aircraft.flight_time
        
        # Log depart
        event = SimulationEvent(
            self.env.now,
            "aircraft",
            "depart",
            {
                "aircraft_id": self.aircraft.aircraft_id,
                "pallet_id": self.aircraft.current_pallet.pallet_id
            }
        )
        print(event.to_json(), file=sys.stdout)
        
        # Wait for flight to complete
        yield self.env.timeout(self.aircraft.flight_time)
        
        # Unload
        self.aircraft.state = "unloading"
        self.aircraft.next_event_time = self.env.now + self.aircraft.unload_time
        
        # Wait for unload to complete
        yield self.env.timeout(self.aircraft.unload_time)
        
        # Log delivery
        latency = self.env.now - self.aircraft.current_pallet.expiration_time + self.aircraft.pallet_expiration_time
        event = SimulationEvent(
            self.env.now,
            "destination",
            "pallet_delivered",
            {
                "pallet_id": self.aircraft.current_pallet.pallet_id,
                "aircraft_id": self.aircraft.aircraft_id,
                "latency": latency
            }
        )
        print(event.to_json(), file=sys.stdout)
        
        # Return
        self.aircraft.state = "returning"
        self.aircraft.next_event_time = self.env.now + self.aircraft.return_time
        
        # Wait for return to complete
        yield self.env.timeout(self.aircraft.return_time)
        
        # Maintenance
        self.aircraft.state = "maintenance"
        self.aircraft.next_event_time = self.env.now + self.aircraft.maintenance_time
        
        # Log maintenance start
        event = SimulationEvent(
            self.env.now,
            "aircraft",
            "maintenance_start",
            {
                "aircraft_id": self.aircraft.aircraft_id
            }
        )
        print(event.to_json(), file=sys.stdout)
        
        # Wait for maintenance to complete
        yield self.env.timeout(self.aircraft.maintenance_time)
        
        # Log maintenance end
        event = SimulationEvent(
            self.env.now,
            "aircraft",
            "maintenance_end",
            {
                "aircraft_id": self.aircraft.aircraft_id
            }
        )
        print(event.to_json(), file=sys.stdout)
        
        # Back to idle
        self.aircraft.state = "idle"
        self.aircraft.current_pallet = None

def aircraft_process(env, aircraft):
    process = AircraftProcess(env, aircraft)
    yield from process.process()

def run_simulation(duration, num_aircraft, pallet_interval, pallet_expiration_time,
                   flight_time, unload_time, return_time, maintenance_time):
    # Create a simulation environment
    env = SimpyEnvironment()
    
    # Create queue
    queue = LoadingQueue(env, None)  # Coordinator will be set later
    
    # Create aircraft
    aircraft_list = []
    for i in range(num_aircraft):
        aircraft = Aircraft(i+1, flight_time, unload_time, return_time, maintenance_time)
        aircraft_list.append(aircraft)
    
    # Create coordinator
    coordinator = Coordinator(env, queue, aircraft_list)
    queue.coordinator = coordinator  # Set coordinator reference
    
    # Create facility
    facility = Facility(env, queue, coordinator, pallet_interval, pallet_expiration_time)
    
    # Start facility process
    env.process(facility.generate_pallet())
    
    # Start aircraft processes
    for aircraft in aircraft_list:
        if aircraft.state == "idle":
            env.process(aircraft_process(env, aircraft))
    
    # Run simulation
    env.run(until=duration)
    
    # Print final statistics
    event = SimulationEvent(
        env.now,
        "system",
        "simulation_complete",
        {
            "duration": duration,
            "num_aircraft": num_aircraft,
            "pallet_interval": pallet_interval,
            "pallet_expiration_time": pallet_expiration_time,
            "flight_time": flight_time,
            "unload_time": unload_time,
            "return_time": return_time,
            "maintenance_time": maintenance_time,
            "total_pallets_generated": facility.pallets_generated,
            "total_expired": queue.total_expired
        }
    )
    print(event.to_json(), file=sys.stdout)

class SimpyEnvironment:
    def __init__(self):
        self.now = 0.0
    
    def process(self, generator):
        # This is a simplified version of simpy's process
        # In a real implementation, this would be more complex
        pass
    
    def timeout(self, delay):
        # This is a simplified version of simpy's timeout
        # In a real implementation, this would be more complex
        return delay
    
    def run(self, until):
        # This is a simplified version of simpy's run
        # In a real implementation, this would be more complex
        self.now = until

def main():
    parser = argparse.ArgumentParser(description="Airfreight Logistics Simulation")
    parser.add_argument("--duration", type=float, default=DEFAULT_DURATION, help="Total simulation time in time units")
    parser.add_argument("--num_aircraft", type=int, default=DEFAULT_NUM_AIRCRAFT, help="Number of aircraft in the system")
    parser.add_argument("--pallet_interval", type=float, default=DEFAULT_PALLET_INTERVAL, help="Time interval between pallet generations")
    parser.add_argument("--pallet_expiration_time", type=float, default=DEFAULT_PALLET_EXPIRATION_TIME, help="Time window for pallet expiration")
    parser.add_argument("--flight_time", type=float, default=DEFAULT_FLIGHT_TIME, help="Flight duration for aircraft transport")
    parser.add_argument("--unload_time", type=float, default=DEFAULT_UNLOAD_TIME, help="Time required for unloading cargo")
    parser.add_argument("--return_time", type=float, default=DEFAULT_RETURN_TIME, help="Return flight duration for aircraft")
    parser.add_argument("--maintenance_time", type=float, default=DEFAULT_MAINTENANCE_TIME, help="Duration of maintenance phase")
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.num_aircraft < 1:
        print("Error: num_aircraft must be >= 1", file=sys.stderr)
        sys.exit(1)
    
    if args.duration <= 0:
        print("Error: duration must be > 0", file=sys.stderr)
        sys.exit(1)
    
    # Run simulation
    run_simulation(
        args.duration,
        args.num_aircraft,
        args.pallet_interval,
        args.pallet_expiration_time,
        args.flight_time,
        args.unload_time,
        args.return_time,
        args.maintenance_time
    )

if __name__ == "__main__":
    main()
</python_code>