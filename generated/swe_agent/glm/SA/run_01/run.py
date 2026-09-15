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
from typing import Dict, List, Optional

try:
    import simpy
except ImportError:
    print("simpy is required. Install it with: pip install simpy", file=sys.stderr)
    sys.exit(1)


# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


class EventLogger:
    """Handles logging events to stdout in JSONL format"""
    
    def __init__(self):
        self.events = []
    
    def log(self, time: float, entity: str, event: str, payload: dict):
        """Log an event"""
        event_obj = {
            "time": time,
            "entity": entity,
            "event": event,
            "payload": payload
        }
        self.events.append(event_obj)
        print(json.dumps(event_obj))
    
    def flush(self):
        """Flush any buffered events"""
        sys.stdout.flush()


class Pallet:
    """Represents a cargo pallet"""
    
    def __init__(self, pallet_id: int, generation_time: float, expiration_time: float):
        self.id = pallet_id
        self.generation_time = generation_time
        self.expiration_time = expiration_time


class LoadingQueue:
    """Manages the loading queue with expiration logic"""
    
    def __init__(self, env: simpy.Environment, logger: EventLogger):
        self.env = env
        self.logger = logger
        self.queue = deque()
        self.pallet_expiration_time = 0.0
        self.total_expired = 0
        self.expiration_processes = {}  # pallet_id -> process
    
    def set_expiration_time(self, expiration_time: float):
        """Set the expiration time for pallets"""
        self.pallet_expiration_time = expiration_time
    
    def add_pallet(self, pallet: Pallet):
        """Add a pallet to the queue and start expiration monitoring"""
        self.queue.append(pallet)
        self.logger.log(
            time=self.env.now,
            entity="queue",
            event="pallet_queued",
            payload={
                "pallet_id": pallet.id,
                "queue_size": len(self.queue)
            }
        )
        
        # Start expiration monitoring for this pallet
        process = self.env.process(self._monitor_expiration(pallet))
        self.expiration_processes[pallet.id] = process
    
    def _monitor_expiration(self, pallet: Pallet):
        """Monitor pallet expiration"""
        try:
            # Wait until expiration time
            yield self.env.timeout(pallet.expiration_time - self.env.now)
            
            # Check if pallet is still in queue
            if pallet in self.queue:
                self.queue.remove(pallet)
                self.total_expired += 1
                self.logger.log(
                    time=self.env.now,
                    entity="queue",
                    event="pallet_expired",
                    payload={
                        "pallet_id": pallet.id,
                        "total_expired": self.total_expired
                    }
                )
        except simpy.Interrupt:
            # Pallet was assigned to aircraft, cancel expiration
            pass
    
    def get_next_pallet(self) -> Optional[Pallet]:
        """Get the next pallet from the queue (FIFO)"""
        if self.queue:
            pallet = self.queue.popleft()
            # Cancel expiration monitoring for this pallet
            if pallet.id in self.expiration_processes:
                self.expiration_processes[pallet.id].interrupt()
                del self.expiration_processes[pallet.id]
            return pallet
        return None
    
    def has_pallets(self) -> bool:
        """Check if there are pallets in the queue"""
        return len(self.queue) > 0


class Aircraft:
    """Represents an aircraft in the fleet"""
    
    def __init__(self, aircraft_id: int, env: simpy.Environment, logger: EventLogger,
                 flight_time: float, unload_time: float, return_time: float, 
                 maintenance_time: float, coordinator):
        self.id = aircraft_id
        self.env = env
        self.logger = logger
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.coordinator = coordinator
        self.state = "idle"  # idle, in_flight, unloading, returning, maintenance
        self.current_pallet = None
    
    def run(self):
        """Main aircraft process"""
        while True:
            # Wait for assignment
            self.state = "idle"
            assignment = yield self.coordinator.get_assignment_store(self.id).get()
            
            if assignment is None:
                # Simulation ending
                break
            
            pallet = assignment
            self.current_pallet = pallet
            
            # Load (instantaneous - 0s)
            # Depart event
            self.logger.log(
                time=self.env.now,
                entity="aircraft",
                event="depart",
                payload={
                    "aircraft_id": self.id,
                    "pallet_id": pallet.id
                }
            )
            
            # Fly to destination
            self.state = "in_flight"
            yield self.env.timeout(self.flight_time)
            
            # Unload cargo
            self.state = "unloading"
            yield self.env.timeout(self.unload_time)
            
            # Delivery happens here
            self.logger.log(
                time=self.env.now,
                entity="destination",
                event="pallet_delivered",
                payload={
                    "pallet_id": pallet.id,
                    "aircraft_id": self.id,
                    "latency": self.env.now - pallet.generation_time
                }
            )
            
            # Return to facility
            self.state = "returning"
            yield self.env.timeout(self.return_time)
            
            # Return event
            self.logger.log(
                time=self.env.now,
                entity="aircraft",
                event="return",
                payload={
                    "aircraft_id": self.id
                }
            )
            
            # Maintenance
            self.state = "maintenance"
            self.logger.log(
                time=self.env.now,
                entity="aircraft",
                event="maintenance_start",
                payload={
                    "aircraft_id": self.id
                }
            )
            yield self.env.timeout(self.maintenance_time)
            
            # Maintenance end
            self.logger.log(
                time=self.env.now,
                entity="aircraft",
                event="maintenance_end",
                payload={
                    "aircraft_id": self.id
                }
            )
            
            self.current_pallet = None
            # Notify coordinator that aircraft is idle
            self.coordinator.aircraft_became_idle(self.id)


class FleetCoordinator:
    """Coordinates aircraft assignments"""
    
    def __init__(self, env: simpy.Environment, logger: EventLogger, num_aircraft: int):
        self.env = env
        self.logger = logger
        self.num_aircraft = num_aircraft
        self.idle_aircraft = set()
        self.assignment_stores = {}  # aircraft_id -> simpy.Store
        self.facility = None  # Will be set later
    
    def set_facility(self, facility):
        """Set reference to facility for assignment notifications"""
        self.facility = facility
    
    def register_aircraft(self, aircraft_id: int):
        """Register an aircraft as idle"""
        self.idle_aircraft.add(aircraft_id)
        self.assignment_stores[aircraft_id] = simpy.Store(self.env)
    
    def get_assignment_store(self, aircraft_id: int):
        """Get the assignment store for an aircraft"""
        return self.assignment_stores[aircraft_id]
    
    def assign_pallet(self, pallet: Pallet) -> bool:
        """Assign a pallet to an idle aircraft"""
        if self.idle_aircraft:
            aircraft_id = self.idle_aircraft.pop()
            
            # Log assignment
            self.logger.log(
                time=self.env.now,
                entity="coordinator",
                event="assignment_created",
                payload={
                    "aircraft_id": aircraft_id,
                    "pallet_id": pallet.id
                }
            )
            
            # Send assignment to aircraft
            self.assignment_stores[aircraft_id].put(pallet)
            return True
        return False
    
    def has_idle_aircraft(self) -> bool:
        """Check if there are idle aircraft"""
        return len(self.idle_aircraft) > 0
    
    def aircraft_became_idle(self, aircraft_id: int):
        """Called when an aircraft becomes idle"""
        self.idle_aircraft.add(aircraft_id)
        # Try to assign queued pallets
        if self.facility:
            self.facility._try_assign_pallets()


class Facility:
    """Generates cargo pallets"""
    
    def __init__(self, env: simpy.Environment, logger: EventLogger, 
                 pallet_interval: float, pallet_expiration_time: float,
                 loading_queue: LoadingQueue, coordinator: FleetCoordinator):
        self.env = env
        self.logger = logger
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.loading_queue = loading_queue
        self.coordinator = coordinator
        self.pallet_counter = 0
    
    def run(self):
        """Generate pallets at regular intervals"""
        while True:
            # Generate new pallet
            self.pallet_counter += 1
            pallet = Pallet(
                pallet_id=self.pallet_counter,
                generation_time=self.env.now,
                expiration_time=self.env.now + self.pallet_expiration_time
            )
            
            # Log generation
            self.logger.log(
                time=self.env.now,
                entity="facility",
                event="pallet_generated",
                payload={
                    "pallet_id": pallet.id,
                    "expiration_time": pallet.expiration_time
                }
            )
            
            # Add to loading queue
            self.loading_queue.add_pallet(pallet)
            
            # Try to assign to idle aircraft
            self._try_assign_pallets()
            
            # Wait for next pallet generation
            yield self.env.timeout(self.pallet_interval)
    
    def _try_assign_pallets(self):
        """Try to assign queued pallets to idle aircraft"""
        while (self.loading_queue.has_pallets() and 
               self.coordinator.has_idle_aircraft()):
            pallet = self.loading_queue.get_next_pallet()
            if pallet:
                self.coordinator.assign_pallet(pallet)


class AirfreightSimulation:
    """Main simulation class"""
    
    def __init__(self, args):
        self.duration = args.duration
        self.num_aircraft = args.num_aircraft
        self.pallet_interval = args.pallet_interval
        self.pallet_expiration_time = args.pallet_expiration_time
        self.flight_time = args.flight_time
        self.unload_time = args.unload_time
        self.return_time = args.return_time
        self.maintenance_time = args.maintenance_time
        
        self.env = simpy.Environment()
        self.logger = EventLogger()
        
        # Create components
        self.loading_queue = LoadingQueue(self.env, self.logger)
        self.loading_queue.set_expiration_time(self.pallet_expiration_time)
        
        self.coordinator = FleetCoordinator(self.env, self.logger, self.num_aircraft)
        
        self.facility = Facility(
            self.env, self.logger, self.pallet_interval, 
            self.pallet_expiration_time, self.loading_queue, self.coordinator
        )
        
        # Set facility reference in coordinator
        self.coordinator.set_facility(self.facility)
        
        # Create aircraft
        self.aircraft = []
        for i in range(1, self.num_aircraft + 1):
            aircraft = Aircraft(
                aircraft_id=i,
                env=self.env,
                logger=self.logger,
                flight_time=self.flight_time,
                unload_time=self.unload_time,
                return_time=self.return_time,
                maintenance_time=self.maintenance_time,
                coordinator=self.coordinator
            )
            self.coordinator.register_aircraft(i)
            self.aircraft.append(aircraft)
    
    def run(self):
        """Run the simulation"""
        logger.info(f"Starting simulation for {self.duration} time units")
        logger.info(f"Configuration: {self.num_aircraft} aircraft, "
                   f"pallet interval: {self.pallet_interval}, "
                   f"expiration time: {self.pallet_expiration_time}")
        
        # Start facility process
        self.env.process(self.facility.run())
        
        # Start aircraft processes
        for aircraft in self.aircraft:
            self.env.process(aircraft.run())
        
        # Run simulation
        self.env.run(until=self.duration)
        
        logger.info(f"Simulation completed at time {self.env.now}")
        self.logger.flush()


def parse_args():
    """Parse command line arguments"""
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
    
    return parser.parse_args()


def main():
    """Main entry point"""
    args = parse_args()
    
    # Validate arguments
    if args.num_aircraft < 1:
        print("Error: num_aircraft must be >= 1", file=sys.stderr)
        sys.exit(1)
    
    # Run simulation
    simulation = AirfreightSimulation(args)
    simulation.run()


if __name__ == "__main__":
    main()