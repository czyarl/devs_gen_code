#!/usr/bin/env python3
"""
Airfreight Logistics Operations Simulation
Discrete Event Simulation using simpy
"""

import argparse
import sys
import json
import logging
from collections import deque
import simpy


class EventLogger:
    """Handles logging events to stdout as JSONL"""
    
    def __init__(self):
        self.logger = logging.getLogger('simulation')
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
    
    def log_event(self, time, entity, event, payload):
        """Log an event to stdout as JSONL"""
        event_obj = {
            "time": time,
            "entity": entity,
            "event": event,
            "payload": payload
        }
        print(json.dumps(event_obj))
    
    def debug(self, message):
        """Log debug message to stderr"""
        self.logger.debug(message)
    
    def info(self, message):
        """Log info message to stderr"""
        self.logger.info(message)
    
    def warning(self, message):
        """Log warning message to stderr"""
        self.logger.warning(message)


class Pallet:
    """Represents a cargo pallet"""
    
    def __init__(self, pallet_id, generation_time, expiration_time):
        self.pallet_id = pallet_id
        self.generation_time = generation_time
        self.expiration_time = expiration_time


class LoadingQueue:
    """Manages the loading queue with expiration logic"""
    
    def __init__(self, env, event_logger):
        self.env = env
        self.event_logger = event_logger
        self.queue = deque()
        self.pallets_in_queue = {}  # pallet_id -> Pallet
        self.total_expired = 0
    
    def add_pallet(self, pallet):
        """Add a pallet to the queue"""
        self.queue.append(pallet.pallet_id)
        self.pallets_in_queue[pallet.pallet_id] = pallet
        
        self.event_logger.log_event(
            self.env.now,
            "queue",
            "pallet_queued",
            {
                "pallet_id": pallet.pallet_id,
                "queue_size": len(self.queue)
            }
        )
        
        # Schedule expiration check
        self.env.process(self._check_expiration(pallet))
    
    def _check_expiration(self, pallet):
        """Check if pallet expires while in queue"""
        yield self.env.timeout(pallet.expiration_time - self.env.now)
        
        # Check if pallet is still in queue
        if pallet.pallet_id in self.pallets_in_queue:
            self.total_expired += 1
            # Remove from queue
            if pallet.pallet_id in self.queue:
                self.queue.remove(pallet.pallet_id)
            del self.pallets_in_queue[pallet.pallet_id]
            
            self.event_logger.log_event(
                self.env.now,
                "queue",
                "pallet_expired",
                {
                    "pallet_id": pallet.pallet_id,
                    "total_expired": self.total_expired
                }
            )
    
    def get_next_pallet(self):
        """Get the next pallet (FIFO)"""
        if self.queue:
            pallet_id = self.queue.popleft()
            pallet = self.pallets_in_queue.pop(pallet_id, None)
            return pallet
        return None
    
    def has_pallets(self):
        """Check if there are pallets in the queue"""
        return len(self.queue) > 0


class Aircraft:
    """Represents an aircraft in the fleet"""
    
    def __init__(self, aircraft_id, env, event_logger, coordinator, 
                 flight_time, unload_time, return_time, maintenance_time):
        self.aircraft_id = aircraft_id
        self.env = env
        self.event_logger = event_logger
        self.coordinator = coordinator
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.state = "idle"
        self.current_pallet = None
    
    def run(self):
        """Main aircraft process"""
        while True:
            # Wait for assignment
            self.state = "idle"
            assignment = yield self.coordinator.get_assignment(self.aircraft_id)
            
            if assignment is None:
                # Simulation ending
                break
            
            self.current_pallet = assignment
            
            # Depart (loading is instantaneous)
            self.event_logger.log_event(
                self.env.now,
                "aircraft",
                "depart",
                {
                    "aircraft_id": self.aircraft_id,
                    "pallet_id": self.current_pallet.pallet_id
                }
            )
            
            # Fly to destination
            self.state = "in-flight"
            yield self.env.timeout(self.flight_time)
            
            # Unload cargo
            self.state = "unloading"
            yield self.env.timeout(self.unload_time)
            
            # Delivery happens here
            latency = self.env.now - self.current_pallet.generation_time
            self.event_logger.log_event(
                self.env.now,
                "destination",
                "pallet_delivered",
                {
                    "pallet_id": self.current_pallet.pallet_id,
                    "aircraft_id": self.aircraft_id,
                    "latency": latency
                }
            )
            
            # Return to facility
            self.state = "returning"
            yield self.env.timeout(self.return_time)
            
            self.event_logger.log_event(
                self.env.now,
                "aircraft",
                "return",
                {
                    "aircraft_id": self.aircraft_id
                }
            )
            
            # Maintenance
            self.state = "maintenance"
            self.event_logger.log_event(
                self.env.now,
                "aircraft",
                "maintenance_start",
                {
                    "aircraft_id": self.aircraft_id
                }
            )
            yield self.env.timeout(self.maintenance_time)
            
            self.event_logger.log_event(
                self.env.now,
                "aircraft",
                "maintenance_end",
                {
                    "aircraft_id": self.aircraft_id
                }
            )
            
            self.current_pallet = None


class FleetCoordinator:
    """Coordinates aircraft and cargo assignments"""
    
    def __init__(self, env, event_logger, loading_queue):
        self.env = env
        self.event_logger = event_logger
        self.loading_queue = loading_queue
        self.assignment_requests = []  # List of (aircraft_id, event) tuples
    
    def get_assignment(self, aircraft_id):
        """Get assignment for an aircraft"""
        request = self.env.event()
        self.assignment_requests.append((aircraft_id, request))
        self._try_assign()
        return request
    
    def _try_assign(self):
        """Try to assign pallets to waiting aircraft"""
        while self.assignment_requests and self.loading_queue.has_pallets():
            aircraft_id, request = self.assignment_requests.pop(0)
            pallet = self.loading_queue.get_next_pallet()
            
            if pallet is not None:
                self.event_logger.log_event(
                    self.env.now,
                    "coordinator",
                    "assignment_created",
                    {
                        "aircraft_id": aircraft_id,
                        "pallet_id": pallet.pallet_id
                    }
                )
                request.succeed(pallet)
            else:
                # No pallet available, put request back
                self.assignment_requests.insert(0, (aircraft_id, request))
                break


class Facility:
    """Generates cargo pallets"""
    
    def __init__(self, env, event_logger, loading_queue, pallet_interval, pallet_expiration_time):
        self.env = env
        self.event_logger = event_logger
        self.loading_queue = loading_queue
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.pallet_counter = 0
    
    def run(self):
        """Generate pallets at regular intervals"""
        while True:
            self.pallet_counter += 1
            pallet_id = self.pallet_counter
            generation_time = self.env.now
            expiration_time = generation_time + self.pallet_expiration_time
            
            pallet = Pallet(pallet_id, generation_time, expiration_time)
            
            self.event_logger.log_event(
                self.env.now,
                "facility",
                "pallet_generated",
                {
                    "pallet_id": pallet_id,
                    "expiration_time": expiration_time
                }
            )
            
            self.loading_queue.add_pallet(pallet)
            
            yield self.env.timeout(self.pallet_interval)


class AirfreightSimulation:
    """Main simulation class"""
    
    def __init__(self, duration, num_aircraft, pallet_interval, pallet_expiration_time,
                 flight_time, unload_time, return_time, maintenance_time):
        self.duration = duration
        self.num_aircraft = num_aircraft
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        
        self.event_logger = EventLogger()
        self.env = simpy.Environment()
        
        # Create components
        self.loading_queue = LoadingQueue(self.env, self.event_logger)
        self.coordinator = FleetCoordinator(self.env, self.event_logger, self.loading_queue)
        self.facility = Facility(self.env, self.event_logger, self.loading_queue,
                                 pallet_interval, pallet_expiration_time)
        self.aircrafts = []
        
        # Create aircraft
        for i in range(1, num_aircraft + 1):
            aircraft = Aircraft(i, self.env, self.event_logger, self.coordinator,
                                flight_time, unload_time, return_time, maintenance_time)
            self.aircrafts.append(aircraft)
    
    def run(self):
        """Run the simulation"""
        self.event_logger.info(f"Starting simulation for {self.duration} time units")
        self.event_logger.info(f"Configuration: {self.num_aircraft} aircraft, "
                              f"pallet interval: {self.pallet_interval}, "
                              f"expiration time: {self.pallet_expiration_time}")
        
        # Start processes
        self.env.process(self.facility.run())
        for aircraft in self.aircrafts:
            self.env.process(aircraft.run())
        
        # Run simulation
        # simpy requires until > current_time (which is 0 at start)
        until_time = max(self.duration, 0.001)
        self.env.run(until=until_time)
        
        self.event_logger.info("Simulation completed")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Airfreight Logistics Operations Simulation')
    
    parser.add_argument('--duration', type=float, default=10000.0,
                        help='Total simulation time in time units')
    parser.add_argument('--num_aircraft', type=int, default=2,
                        help='Number of aircraft in the system')
    parser.add_argument('--pallet_interval', type=float, default=25.0,
                        help='Time interval between pallet generations')
    parser.add_argument('--pallet_expiration_time', type=float, default=150.0,
                        help='Time window for pallet expiration')
    parser.add_argument('--flight_time', type=float, default=30.0,
                        help='Flight duration for aircraft transport')
    parser.add_argument('--unload_time', type=float, default=2.0,
                        help='Time required for unloading cargo')
    parser.add_argument('--return_time', type=float, default=30.0,
                        help='Return flight duration')
    parser.add_argument('--maintenance_time', type=float, default=10.0,
                        help='Duration of maintenance phase')
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.num_aircraft < 1:
        print("Error: num_aircraft must be >= 1", file=sys.stderr)
        sys.exit(1)
    
    # Create and run simulation
    sim = AirfreightSimulation(
        duration=args.duration,
        num_aircraft=args.num_aircraft,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
        flight_time=args.flight_time,
        unload_time=args.unload_time,
        return_time=args.return_time,
        maintenance_time=args.maintenance_time
    )
    
    sim.run()


if __name__ == '__main__':
    main()