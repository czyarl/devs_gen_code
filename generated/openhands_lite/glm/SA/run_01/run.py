#!/usr/bin/env python3
"""
Airfreight Logistics Operations Simulation
Discrete Event Simulation using simpy library
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


class Pallet:
    """Represents a cargo pallet with ID and expiration time."""
    def __init__(self, pallet_id, generation_time, expiration_time):
        self.pallet_id = pallet_id
        self.generation_time = generation_time
        self.expiration_time = expiration_time


class LoadingQueue:
    """Manages the loading queue with expiration checking."""
    def __init__(self, env, pallet_expiration_time, log_event):
        self.env = env
        self.pallet_expiration_time = pallet_expiration_time
        self.log_event = log_event
        self.queue = deque()
        self.total_expired = 0
        self.expiration_events = {}  # pallet_id -> event

    def add_pallet(self, pallet):
        """Add a pallet to the queue and schedule expiration check."""
        self.queue.append(pallet)
        self.log_event(
            "queue",
            "pallet_queued",
            {
                "pallet_id": pallet.pallet_id,
                "queue_size": len(self.queue)
            }
        )
        # Schedule expiration event
        time_to_expiration = pallet.expiration_time - self.env.now
        if time_to_expiration > 0:
            event = self.env.timeout(time_to_expiration)
            self.expiration_events[pallet.pallet_id] = event
            self.env.process(self._check_expiration(pallet, event))

    def _check_expiration(self, pallet, expiration_event):
        """Check if pallet expires while in queue."""
        yield expiration_event
        # Check if pallet is still in queue
        if pallet in self.queue:
            self.queue.remove(pallet)
            self.total_expired += 1
            self.log_event(
                "queue",
                "pallet_expired",
                {
                    "pallet_id": pallet.pallet_id,
                    "total_expired": self.total_expired
                }
            )

    def get_next_pallet(self):
        """Get next pallet from queue (FIFO)."""
        if self.queue:
            pallet = self.queue.popleft()
            # Cancel expiration event if still pending
            if pallet.pallet_id in self.expiration_events:
                del self.expiration_events[pallet.pallet_id]
            return pallet
        return None

    def has_pallets(self):
        """Check if queue has pallets."""
        return len(self.queue) > 0

    def size(self):
        """Return current queue size."""
        return len(self.queue)


class Aircraft:
    """Represents an aircraft with cyclic operations."""
    def __init__(self, env, aircraft_id, flight_time, unload_time, return_time, 
                 maintenance_time, log_event):
        self.env = env
        self.aircraft_id = aircraft_id
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.log_event = log_event
        self.state = "idle"
        self.current_pallet = None
        self.coordinator = None

    def set_coordinator(self, coordinator):
        """Set reference to fleet coordinator."""
        self.coordinator = coordinator

    def run(self):
        """Main aircraft process."""
        while True:
            # Wait for assignment
            self.state = "idle"
            assignment = yield self.coordinator.get_assignment(self.aircraft_id)
            
            if assignment is None:
                # Simulation ending
                break
            
            self.current_pallet = assignment
            
            # Load (instantaneous)
            self.log_event(
                "aircraft",
                "depart",
                {
                    "aircraft_id": self.aircraft_id,
                    "pallet_id": self.current_pallet.pallet_id
                }
            )
            
            # Fly to destination
            self.state = "flying"
            yield self.env.timeout(self.flight_time)
            
            # Unload at destination
            self.state = "unloading"
            yield self.env.timeout(self.unload_time)
            
            # Delivery happens here
            latency = self.env.now - self.current_pallet.generation_time
            self.log_event(
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
            
            self.log_event(
                "aircraft",
                "return",
                {
                    "aircraft_id": self.aircraft_id
                }
            )
            
            # Maintenance
            self.state = "maintenance"
            self.log_event(
                "aircraft",
                "maintenance_start",
                {
                    "aircraft_id": self.aircraft_id
                }
            )
            yield self.env.timeout(self.maintenance_time)
            
            self.log_event(
                "aircraft",
                "maintenance_end",
                {
                    "aircraft_id": self.aircraft_id
                }
            )
            
            self.current_pallet = None


class FleetCoordinator:
    """Coordinates aircraft assignments."""
    def __init__(self, env, num_aircraft, log_event):
        self.env = env
        self.num_aircraft = num_aircraft
        self.log_event = log_event
        self.aircraft_status = {i: "idle" for i in range(num_aircraft)}
        self.assignment_requests = {}  # aircraft_id -> event

    def update_aircraft_status(self, aircraft_id, status):
        """Update aircraft status."""
        self.aircraft_status[aircraft_id] = status

    def get_assignment(self, aircraft_id):
        """Aircraft requests assignment."""
        event = self.env.event()
        self.assignment_requests[aircraft_id] = event
        self.update_aircraft_status(aircraft_id, "waiting")
        return event

    def assign_pallet(self, aircraft_id, pallet):
        """Assign pallet to aircraft."""
        if aircraft_id in self.assignment_requests:
            self.assignment_requests[aircraft_id].succeed(pallet)
            del self.assignment_requests[aircraft_id]
            self.update_aircraft_status(aircraft_id, "assigned")
            self.log_event(
                "coordinator",
                "assignment_created",
                {
                    "aircraft_id": aircraft_id,
                    "pallet_id": pallet.pallet_id
                }
            )

    def get_idle_aircraft(self):
        """Get list of idle aircraft IDs."""
        return [aid for aid, status in self.aircraft_status.items() 
                if status == "idle"]

    def has_idle_aircraft(self):
        """Check if any aircraft is idle."""
        return any(status == "idle" for status in self.aircraft_status.values())


class Facility:
    """Generates pallets at regular intervals."""
    def __init__(self, env, pallet_interval, pallet_expiration_time, 
                 loading_queue, log_event):
        self.env = env
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.loading_queue = loading_queue
        self.log_event = log_event
        self.pallet_counter = 0

    def run(self):
        """Generate pallets at regular intervals."""
        while True:
            self.pallet_counter += 1
            pallet_id = self.pallet_counter
            generation_time = self.env.now
            expiration_time = generation_time + self.pallet_expiration_time
            
            pallet = Pallet(pallet_id, generation_time, expiration_time)
            
            self.log_event(
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
    """Run the airfreight logistics simulation."""
    # Create simpy environment
    env = simpy.Environment()
    
    # Event logging function
    def log_event(entity, event, payload):
        event_data = {
            "time": env.now,
            "entity": entity,
            "event": event,
            "payload": payload
        }
        print(json.dumps(event_data))
    
    # Create entities
    loading_queue = LoadingQueue(env, args.pallet_expiration_time, log_event)
    coordinator = FleetCoordinator(env, args.num_aircraft, log_event)
    
    # Create aircraft
    aircraft_list = []
    for i in range(args.num_aircraft):
        aircraft = Aircraft(
            env, i, args.flight_time, args.unload_time, 
            args.return_time, args.maintenance_time, log_event
        )
        aircraft.set_coordinator(coordinator)
        aircraft_list.append(aircraft)
        env.process(aircraft.run())
    
    # Create facility
    facility = Facility(
        env, args.pallet_interval, args.pallet_expiration_time,
        loading_queue, log_event
    )
    env.process(facility.run())
    
    # Coordinator process: assign pallets to aircraft
    def coordinator_process():
        while True:
            # Check if we have pallets and idle aircraft
            if loading_queue.has_pallets() and coordinator.has_idle_aircraft():
                pallet = loading_queue.get_next_pallet()
                idle_aircraft = coordinator.get_idle_aircraft()[0]
                coordinator.assign_pallet(idle_aircraft, pallet)
            
            # Check again after a short delay
            yield env.timeout(0.01)
    
    env.process(coordinator_process())
    
    # Run simulation
    logger.info(f"Starting simulation for {args.duration} time units")
    logger.info(f"Parameters: num_aircraft={args.num_aircraft}, "
                f"pallet_interval={args.pallet_interval}, "
                f"pallet_expiration_time={args.pallet_expiration_time}")
    
    env.run(until=args.duration)
    
    logger.info(f"Simulation completed at time {env.now}")
    logger.info(f"Total pallets generated: {facility.pallet_counter}")
    logger.info(f"Total pallets expired: {loading_queue.total_expired}")


def main():
    """Main entry point."""
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
