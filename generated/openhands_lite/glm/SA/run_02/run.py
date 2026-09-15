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

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


class EventLogger:
    """Handles logging of simulation events to stdout as JSONL"""
    
    def __init__(self):
        pass
    
    def log(self, time, entity, event, payload):
        """Log an event to stdout"""
        event_obj = {
            "time": time,
            "entity": entity,
            "event": event,
            "payload": payload
        }
        print(json.dumps(event_obj))
        sys.stdout.flush()


class Pallet:
    """Represents a cargo pallet"""
    
    def __init__(self, pallet_id, generation_time, expiration_time):
        self.id = pallet_id
        self.generation_time = generation_time
        self.expiration_time = expiration_time


class LoadingQueue:
    """Manages the loading queue with expiration monitoring"""
    
    def __init__(self, env, event_logger):
        self.env = env
        self.event_logger = event_logger
        self.queue = deque()
        self.pallets = {}  # pallet_id -> Pallet
        self.total_expired = 0
        self.expiration_process = env.process(self._monitor_expirations())
    
    def add_pallet(self, pallet):
        """Add a pallet to the queue"""
        self.queue.append(pallet.id)
        self.pallets[pallet.id] = pallet
        self.event_logger.log(
            self.env.now,
            "queue",
            "pallet_queued",
            {
                "pallet_id": pallet.id,
                "queue_size": len(self.queue)
            }
        )
    
    def get_next_pallet(self):
        """Get the next pallet (FIFO)"""
        if self.queue:
            pallet_id = self.queue.popleft()
            pallet = self.pallets.pop(pallet_id, None)
            return pallet
        return None
    
    def remove_pallet(self, pallet_id):
        """Remove a specific pallet from queue"""
        if pallet_id in self.pallets:
            self.pallets.pop(pallet_id)
            if pallet_id in self.queue:
                self.queue.remove(pallet_id)
    
    def _monitor_expirations(self):
        """Monitor and expire pallets that exceed their deadline"""
        while True:
            current_time = self.env.now
            
            # Check for expired pallets
            expired_pallets = []
            for pallet_id, pallet in list(self.pallets.items()):
                if current_time >= pallet.expiration_time:
                    expired_pallets.append(pallet_id)
            
            # Process expired pallets
            for pallet_id in expired_pallets:
                self.remove_pallet(pallet_id)
                self.total_expired += 1
                self.event_logger.log(
                    current_time,
                    "queue",
                    "pallet_expired",
                    {
                        "pallet_id": pallet_id,
                        "total_expired": self.total_expired
                    }
                )
            
            # Check again after a small time step
            yield self.env.timeout(0.1)
    
    def has_pallets(self):
        """Check if there are pallets in the queue"""
        return len(self.queue) > 0


class Aircraft:
    """Represents an aircraft in the fleet"""
    
    def __init__(self, aircraft_id, env, event_logger, destination, flight_time, unload_time, 
                 return_time, maintenance_time):
        self.id = aircraft_id
        self.env = env
        self.event_logger = event_logger
        self.destination = destination
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.state = "idle"
        self.current_pallet = None
        self.operation_process = None
    
    def start_operation(self):
        """Start the aircraft operation cycle"""
        self.operation_process = self.env.process(self._operation_cycle())
    
    def _operation_cycle(self):
        """Main aircraft operation cycle"""
        while True:
            # Wait idle until assigned
            self.state = "idle"
            yield self.env.timeout(0.1)
            
            # If assigned a pallet, begin transport
            if self.current_pallet is not None:
                # Load (instantaneous, 0s)
                self.event_logger.log(
                    self.env.now,
                    "aircraft",
                    "depart",
                    {
                        "aircraft_id": self.id,
                        "pallet_id": self.current_pallet.id
                    }
                )
                
                # Fly to destination
                self.state = "in-flight"
                yield self.env.timeout(self.flight_time)
                
                # Unload cargo
                self.state = "unloading"
                yield self.env.timeout(self.unload_time)
                
                # Delivery happens here - record with destination
                self.state = "delivering"
                self.destination.receive_delivery(self.current_pallet, self.id)
                
                # Return to facility
                self.state = "returning"
                yield self.env.timeout(self.return_time)
                
                self.event_logger.log(
                    self.env.now,
                    "aircraft",
                    "return",
                    {
                        "aircraft_id": self.id
                    }
                )
                
                # Maintenance
                self.state = "maintenance"
                self.event_logger.log(
                    self.env.now,
                    "aircraft",
                    "maintenance_start",
                    {
                        "aircraft_id": self.id
                    }
                )
                yield self.env.timeout(self.maintenance_time)
                
                self.event_logger.log(
                    self.env.now,
                    "aircraft",
                    "maintenance_end",
                    {
                        "aircraft_id": self.id
                    }
                )
                
                # Clear current pallet and return to idle
                self.current_pallet = None
                self.state = "idle"
    
    def assign_pallet(self, pallet):
        """Assign a pallet to this aircraft"""
        self.current_pallet = pallet
    
    def is_idle(self):
        """Check if aircraft is idle and available"""
        return self.state == "idle" and self.current_pallet is None


class FleetCoordinator:
    """Coordinates aircraft assignments"""
    
    def __init__(self, env, event_logger, loading_queue, aircraft_list):
        self.env = env
        self.event_logger = event_logger
        self.loading_queue = loading_queue
        self.aircraft_list = aircraft_list
        self.coordination_process = env.process(self._coordinate())
    
    def _coordinate(self):
        """Continuously check for assignments"""
        while True:
            # Check if there are pallets and idle aircraft
            if self.loading_queue.has_pallets():
                for aircraft in self.aircraft_list:
                    if aircraft.is_idle():
                        pallet = self.loading_queue.get_next_pallet()
                        if pallet is not None:
                            # Assign pallet to aircraft
                            aircraft.assign_pallet(pallet)
                            self.event_logger.log(
                                self.env.now,
                                "coordinator",
                                "assignment_created",
                                {
                                    "aircraft_id": aircraft.id,
                                    "pallet_id": pallet.id
                                }
                            )
                            break
            
            yield self.env.timeout(0.1)


class Destination:
    """Receives delivered cargo"""
    
    def __init__(self, env, event_logger):
        self.env = env
        self.event_logger = event_logger
    
    def receive_delivery(self, pallet, aircraft_id):
        """Record a successful delivery"""
        latency = self.env.now - pallet.generation_time
        self.event_logger.log(
            self.env.now,
            "destination",
            "pallet_delivered",
            {
                "pallet_id": pallet.id,
                "aircraft_id": aircraft_id,
                "latency": latency
            }
        )


class Facility:
    """Generates cargo pallets"""
    
    def __init__(self, env, event_logger, loading_queue, pallet_interval, 
                 pallet_expiration_time):
        self.env = env
        self.event_logger = event_logger
        self.loading_queue = loading_queue
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.pallet_counter = 0
        self.generation_process = env.process(self._generate_pallets())
    
    def _generate_pallets(self):
        """Generate pallets at regular intervals"""
        while True:
            self.pallet_counter += 1
            pallet_id = self.pallet_counter
            generation_time = self.env.now
            expiration_time = generation_time + self.pallet_expiration_time
            
            pallet = Pallet(pallet_id, generation_time, expiration_time)
            
            self.event_logger.log(
                generation_time,
                "facility",
                "pallet_generated",
                {
                    "pallet_id": pallet_id,
                    "expiration_time": expiration_time
                }
            )
            
            self.loading_queue.add_pallet(pallet)
            
            yield self.env.timeout(self.pallet_interval)


def run_simulation(args):
    """Run the airfreight logistics simulation"""
    
    # Create simpy environment
    env = simpy.Environment()
    
    # Create event logger
    event_logger = EventLogger()
    
    # Create loading queue
    loading_queue = LoadingQueue(env, event_logger)
    
    # Create destination
    destination = Destination(env, event_logger)
    
    # Create aircraft
    aircraft_list = []
    for i in range(args.num_aircraft):
        aircraft = Aircraft(
            aircraft_id=i + 1,
            env=env,
            event_logger=event_logger,
            destination=destination,
            flight_time=args.flight_time,
            unload_time=args.unload_time,
            return_time=args.return_time,
            maintenance_time=args.maintenance_time
        )
        aircraft.start_operation()
        aircraft_list.append(aircraft)
    
    # Create fleet coordinator
    coordinator = FleetCoordinator(env, event_logger, loading_queue, aircraft_list)
    
    # Create facility
    facility = Facility(
        env=env,
        event_logger=event_logger,
        loading_queue=loading_queue,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time
    )
    
    # Run simulation
    logger.info(f"Starting simulation for {args.duration} time units")
    env.run(until=args.duration)
    logger.info("Simulation completed")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Airfreight Logistics Operations Simulation"
    )
    
    parser.add_argument(
        "--duration",
        type=float,
        default=10000.0,
        help="Total simulation time in time units"
    )
    
    parser.add_argument(
        "--num_aircraft",
        type=int,
        default=2,
        help="Number of aircraft in the system"
    )
    
    parser.add_argument(
        "--pallet_interval",
        type=float,
        default=25.0,
        help="Time interval between pallet generations"
    )
    
    parser.add_argument(
        "--pallet_expiration_time",
        type=float,
        default=150.0,
        help="Time window for pallet expiration"
    )
    
    parser.add_argument(
        "--flight_time",
        type=float,
        default=30.0,
        help="Flight duration for aircraft transport"
    )
    
    parser.add_argument(
        "--unload_time",
        type=float,
        default=2.0,
        help="Time required for unloading cargo"
    )
    
    parser.add_argument(
        "--return_time",
        type=float,
        default=30.0,
        help="Return flight duration"
    )
    
    parser.add_argument(
        "--maintenance_time",
        type=float,
        default=10.0,
        help="Duration of maintenance phase"
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.num_aircraft < 1:
        logger.error("num_aircraft must be >= 1")
        sys.exit(1)
    
    # Run simulation
    run_simulation(args)


if __name__ == "__main__":
    main()