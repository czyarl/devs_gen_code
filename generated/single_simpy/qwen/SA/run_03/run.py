import argparse
import sys
import json
import logging
import random
from collections import deque
import time

# Simulation environment using simpy for discrete event simulation
import simpy

# Global variables for simulation parameters
simulation_params = {}

# Event types
EVENT_TYPES = {
    "pallet_generated": "facility",
    "pallet_queued": "queue",
    "pallet_expired": "queue",
    "assignment_created": "coordinator",
    "depart": "aircraft",
    "return": "aircraft",
    "maintenance_start": "aircraft",
    "maintenance_end": "aircraft",
    "pallet_delivered": "destination"
}

class SimulationLogger:
    def __init__(self):
        self.events = []
    
    def log(self, time, entity, event, payload):
        event_obj = {
            "time": time,
            "entity": entity,
            "event": event,
            "payload": payload
        }
        self.events.append(event_obj)
        print(json.dumps(event_obj), file=sys.stdout)

# Global logger instance
logger = SimulationLogger()

class Pallet:
    def __init__(self, pallet_id, expiration_time):
        self.pallet_id = pallet_id
        self.expiration_time = expiration_time

class Facility:
    def __init__(self, env, queue, pallet_generator):
        self.env = env
        self.queue = queue
        self.pallet_generator = pallet_generator
        self.pallet_counter = 0
        self.pallet_interval = simulation_params['pallet_interval']
        self.pallet_expiration_time = simulation_params['pallet_expiration_time']
    
    def generate_pallet(self):
        while True:
            yield self.env.timeout(self.pallet_interval)
            self.pallet_counter += 1
            expiration_time = self.env.now + self.pallet_expiration_time
            pallet = Pallet(self.pallet_counter, expiration_time)
            logger.log(self.env.now, "facility", "pallet_generated", {
                "pallet_id": pallet.pallet_id,
                "expiration_time": expiration_time
            })
            self.pallet_generator.put(pallet)

class LoadingQueue:
    def __init__(self, env, coordinator):
        self.env = env
        self.coordinator = coordinator
        self.queue = deque()
        self.expired_count = 0
    
    def put(self, pallet):
        self.queue.append(pallet)
        logger.log(self.env.now, "queue", "pallet_queued", {
            "pallet_id": pallet.pallet_id,
            "queue_size": len(self.queue)
        })
        self.check_expiration(pallet)
        self.coordinator.check_assignment()
    
    def get(self):
        if self.queue:
            pallet = self.queue.popleft()
            logger.log(self.env.now, "queue", "pallet_dequeued", {
                "pallet_id": pallet.pallet_id,
                "queue_size": len(self.queue)
            })
            return pallet
        return None
    
    def check_expiration(self, pallet):
        if self.env.now > pallet.expiration_time:
            self.expire_pallet(pallet)
        else:
            # Schedule expiration check
            yield self.env.timeout(pallet.expiration_time - self.env.now)
            if self.queue and self.queue[0] == pallet:
                self.expire_pallet(pallet)
    
    def expire_pallet(self, pallet):
        if pallet in self.queue:
            self.queue.remove(pallet)
            self.expired_count += 1
            logger.log(self.env.now, "queue", "pallet_expired", {
                "pallet_id": pallet.pallet_id,
                "total_expired": self.expired_count
            })

class FleetCoordinator:
    def __init__(self, env, queue, aircraft_list):
        self.env = env
        self.queue = queue
        self.aircraft_list = aircraft_list
        self.assignment_lock = simpy.Resource(env, capacity=1)
    
    def check_assignment(self):
        # Check if there are pallets in queue and aircraft available
        if self.queue.queue and any(not aircraft.is_idle for aircraft in self.aircraft_list):
            # Find an idle aircraft
            for aircraft in self.aircraft_list:
                if aircraft.is_idle:
                    # Assign the pallet to this aircraft
                    pallet = self.queue.get()
                    if pallet:
                        logger.log(self.env.now, "coordinator", "assignment_created", {
                            "aircraft_id": aircraft.aircraft_id,
                            "pallet_id": pallet.pallet_id
                        })
                        aircraft.assign_pallet(pallet)
                        break

class Aircraft:
    def __init__(self, env, aircraft_id, coordinator, destination):
        self.env = env
        self.aircraft_id = aircraft_id
        self.coordinator = coordinator
        self.destination = destination
        self.is_idle = True
        self.current_pallet = None
        self.flight_time = simulation_params['flight_time']
        self.unload_time = simulation_params['unload_time']
        self.return_time = simulation_params['return_time']
        self.maintenance_time = simulation_params['maintenance_time']
    
    def assign_pallet(self, pallet):
        self.is_idle = False
        self.current_pallet = pallet
        logger.log(self.env.now, "aircraft", "depart", {
            "aircraft_id": self.aircraft_id,
            "pallet_id": pallet.pallet_id
        })
        # Start the transport cycle
        self.env.process(self.transport_cycle())
    
    def transport_cycle(self):
        # Load (instantaneous)
        # Fly to destination
        yield self.env.timeout(self.flight_time)
        # Unload
        yield self.env.timeout(self.unload_time)
        # Record delivery
        latency = self.env.now - self.current_pallet.expiration_time + simulation_params['pallet_expiration_time']
        logger.log(self.env.now, "destination", "pallet_delivered", {
            "pallet_id": self.current_pallet.pallet_id,
            "aircraft_id": self.aircraft_id,
            "latency": latency
        })
        # Return to facility
        yield self.env.timeout(self.return_time)
        logger.log(self.env.now, "aircraft", "return", {
            "aircraft_id": self.aircraft_id
        })
        # Maintenance
        yield self.env.timeout(self.maintenance_time)
        logger.log(self.env.now, "aircraft", "maintenance_end", {
            "aircraft_id": self.aircraft_id
        })
        # Aircraft is now idle again
        self.is_idle = True
        self.current_pallet = None
        self.coordinator.check_assignment()

def run_simulation(duration, num_aircraft, pallet_interval, pallet_expiration_time,
                   flight_time, unload_time, return_time, maintenance_time):
    # Set global simulation parameters
    global simulation_params
    simulation_params = {
        'duration': duration,
        'num_aircraft': num_aircraft,
        'pallet_interval': pallet_interval,
        'pallet_expiration_time': pallet_expiration_time,
        'flight_time': flight_time,
        'unload_time': unload_time,
        'return_time': return_time,
        'maintenance_time': maintenance_time
    }
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create components
    queue = LoadingQueue(env, None)  # Coordinator will be set later
    coordinator = FleetCoordinator(env, queue, [])
    aircraft_list = []
    
    # Set up aircraft
    for i in range(num_aircraft):
        aircraft = Aircraft(env, i+1, coordinator, None)
        aircraft_list.append(aircraft)
    
    # Set coordinator's aircraft list
    coordinator.aircraft_list = aircraft_list
    
    # Set up queue with coordinator
    queue.coordinator = coordinator
    
    # Create facility
    facility = Facility(env, queue, queue)
    
    # Start facility process
    env.process(facility.generate_pallet())
    
    # Run simulation
    env.run(until=duration)
    
    # Print final state (if any)
    return logger.events

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
    
    # Validate arguments
    if args.num_aircraft < 1:
        print("Error: num_aircraft must be at least 1", file=sys.stderr)
        sys.exit(1)
    if args.duration <= 0:
        print("Error: duration must be positive", file=sys.stderr)
        sys.exit(1)
    if args.pallet_interval <= 0:
        print("Error: pallet_interval must be positive", file=sys.stderr)
        sys.exit(1)
    if args.pallet_expiration_time <= 0:
        print("Error: pallet_expiration_time must be positive", file=sys.stderr)
        sys.exit(1)
    if args.flight_time <= 0:
        print("Error: flight_time must be positive", file=sys.stderr)
        sys.exit(1)
    if args.unload_time <= 0:
        print("Error: unload_time must be positive", file=sys.stderr)
        sys.exit(1)
    if args.return_time <= 0:
        print("Error: return_time must be positive", file=sys.stderr)
        sys.exit(1)
    if args.maintenance_time <= 0:
        print("Error: maintenance_time must be positive", file=sys.stderr)
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