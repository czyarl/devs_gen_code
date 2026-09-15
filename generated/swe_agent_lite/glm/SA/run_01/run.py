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


class EventLogger:
    """Handles logging of simulation events to stdout in JSONL format."""
    
    def __init__(self):
        self.logger = logging.getLogger('simulation')
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger.addHandler(handler)
    
    def log_event(self, time, entity, event, payload):
        """Log an event to stdout as JSONL."""
        event_obj = {
            "time": time,
            "entity": entity,
            "event": event,
            "payload": payload
        }
        print(json.dumps(event_obj))
        self.logger.debug(f"{entity}: {event} - {payload}")


class Pallet:
    """Represents a cargo pallet with ID and expiration time."""
    
    def __init__(self, pallet_id, generation_time, expiration_time):
        self.pallet_id = pallet_id
        self.generation_time = generation_time
        self.expiration_time = expiration_time


class LoadingQueue:
    """Manages the loading queue with active expiration monitoring."""
    
    def __init__(self, env, event_logger):
        self.env = env
        self.event_logger = event_logger
        self.queue = deque()
        self.pallets = {}  # pallet_id -> Pallet object
        self.total_expired = 0
        self.expiration_process = env.process(self._monitor_expirations())
    
    def add_pallet(self, pallet):
        """Add a pallet to the queue."""
        self.queue.append(pallet.pallet_id)
        self.pallets[pallet.pallet_id] = pallet
        self.event_logger.log_event(
            self.env.now,
            "queue",
            "pallet_queued",
            {
                "pallet_id": pallet.pallet_id,
                "queue_size": len(self.queue)
            }
        )
    
    def get_next_pallet(self):
        """Get the next pallet (FIFO) if available."""
        if self.queue:
            pallet_id = self.queue.popleft()
            pallet = self.pallets.pop(pallet_id)
            return pallet
        return None
    
    def has_pallets(self):
        """Check if there are pallets in the queue."""
        return len(self.queue) > 0
    
    def _monitor_expirations(self):
        """Monitor and expire pallets when their deadline is reached."""
        while True:
            # Check for expired pallets
            current_time = self.env.now
            expired_ids = []
            
            for pallet_id, pallet in list(self.pallets.items()):
                if current_time >= pallet.expiration_time:
                    expired_ids.append(pallet_id)
            
            # Remove expired pallets
            for pallet_id in expired_ids:
                if pallet_id in self.pallets:
                    # Remove from queue if still there
                    if pallet_id in self.queue:
                        self.queue.remove(pallet_id)
                    self.pallets.pop(pallet_id)
                    self.total_expired += 1
                    self.event_logger.log_event(
                        self.env.now,
                        "queue",
                        "pallet_expired",
                        {
                            "pallet_id": pallet_id,
                            "total_expired": self.total_expired
                        }
                    )
            
            # Check again after a small time step
            yield self.env.timeout(0.1)


class Aircraft:
    """Represents an aircraft with cyclic operation states."""
    
    def __init__(self, env, aircraft_id, event_logger, flight_time, unload_time, 
                 return_time, maintenance_time, coordinator):
        self.env = env
        self.aircraft_id = aircraft_id
        self.event_logger = event_logger
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.coordinator = coordinator
        self.current_pallet = None
        self.state = "idle"
        self.process = env.process(self._run())
    
    def _run(self):
        """Main aircraft process handling state transitions."""
        while True:
            # Wait idle until assigned
            self.state = "idle"
            yield self.env.timeout(0)  # Yield control
            
            # Wait for assignment
            while self.current_pallet is None:
                yield self.env.timeout(0.1)
            
            # Load (instantaneous - 0s)
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
            self.event_logger.log_event(
                self.env.now,
                "destination",
                "pallet_delivered",
                {
                    "pallet_id": self.current_pallet.pallet_id,
                    "aircraft_id": self.aircraft_id,
                    "latency": self.env.now - self.current_pallet.generation_time
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
            
            # Clear current pallet and notify coordinator
            self.current_pallet = None
            self.coordinator.notify_aircraft_available(self.aircraft_id)
    
    def assign_pallet(self, pallet):
        """Assign a pallet to this aircraft."""
        self.current_pallet = pallet
    
    def is_idle(self):
        """Check if aircraft is idle and available."""
        return self.state == "idle" and self.current_pallet is None


class FleetCoordinator:
    """Coordinates aircraft assignments based on availability and demand."""
    
    def __init__(self, env, event_logger, loading_queue, aircraft_list):
        self.env = env
        self.event_logger = event_logger
        self.loading_queue = loading_queue
        self.aircraft_list = aircraft_list
        self.aircraft_map = {ac.aircraft_id: ac for ac in aircraft_list}
        self.process = env.process(self._coordinate())
    
    def _coordinate(self):
        """Main coordination process."""
        while True:
            # Check if we have both available aircraft and queued pallets
            available_aircraft = [ac for ac in self.aircraft_list if ac.is_idle()]
            
            while available_aircraft and self.loading_queue.has_pallets():
                aircraft = available_aircraft.pop(0)
                pallet = self.loading_queue.get_next_pallet()
                
                if pallet:
                    # Assign pallet to aircraft
                    aircraft.assign_pallet(pallet)
                    self.event_logger.log_event(
                        self.env.now,
                        "coordinator",
                        "assignment_created",
                        {
                            "aircraft_id": aircraft.aircraft_id,
                            "pallet_id": pallet.pallet_id
                        }
                    )
            
            # Check again after a small delay
            yield self.env.timeout(0.1)
    
    def notify_aircraft_available(self, aircraft_id):
        """Called when an aircraft becomes available."""
        pass  # The coordinator will check on next iteration


class Facility:
    """Generates cargo pallets at regular intervals."""
    
    def __init__(self, env, event_logger, loading_queue, pallet_interval, 
                 pallet_expiration_time):
        self.env = env
        self.event_logger = event_logger
        self.loading_queue = loading_queue
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.next_pallet_id = 1
        self.process = env.process(self._generate_pallets())
    
    def _generate_pallets(self):
        """Generate pallets at regular intervals."""
        while True:
            # Generate new pallet
            generation_time = self.env.now
            expiration_time = generation_time + self.pallet_expiration_time
            pallet_id = self.next_pallet_id
            
            self.event_logger.log_event(
                generation_time,
                "facility",
                "pallet_generated",
                {
                    "pallet_id": pallet_id,
                    "expiration_time": expiration_time
                }
            )
            
            # Create pallet and add to queue
            pallet = Pallet(pallet_id, generation_time, expiration_time)
            self.loading_queue.add_pallet(pallet)
            
            self.next_pallet_id += 1
            
            # Wait for next generation
            yield self.env.timeout(self.pallet_interval)


class AirfreightSimulation:
    """Main simulation orchestrator."""
    
    def __init__(self, duration, num_aircraft, pallet_interval, 
                 pallet_expiration_time, flight_time, unload_time, 
                 return_time, maintenance_time):
        self.duration = duration
        self.num_aircraft = num_aircraft
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.event_logger = EventLogger()
    
    def run(self):
        """Run the simulation."""
        # Create simpy environment
        env = simpy.Environment()
        
        # Create loading queue
        loading_queue = LoadingQueue(env, self.event_logger)
        
        # Create aircraft
        aircraft_list = []
        for i in range(1, self.num_aircraft + 1):
            aircraft = Aircraft(
                env, i, self.event_logger, self.flight_time, self.unload_time,
                self.return_time, self.maintenance_time, None
            )
            aircraft_list.append(aircraft)
        
        # Create fleet coordinator
        coordinator = FleetCoordinator(env, self.event_logger, loading_queue, aircraft_list)
        
        # Update aircraft coordinator references
        for aircraft in aircraft_list:
            aircraft.coordinator = coordinator
        
        # Create facility
        facility = Facility(
            env, self.event_logger, loading_queue, self.pallet_interval,
            self.pallet_expiration_time
        )
        
        # Run simulation
        env.run(until=self.duration)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Airfreight Logistics Operations Simulation'
    )
    
    parser.add_argument(
        '--duration',
        type=float,
        default=10000.0,
        help='Total simulation time in time units'
    )
    
    parser.add_argument(
        '--num_aircraft',
        type=int,
        default=2,
        help='Number of aircraft in the system'
    )
    
    parser.add_argument(
        '--pallet_interval',
        type=float,
        default=25.0,
        help='Time interval between pallet generations'
    )
    
    parser.add_argument(
        '--pallet_expiration_time',
        type=float,
        default=150.0,
        help='Time window for pallet expiration'
    )
    
    parser.add_argument(
        '--flight_time',
        type=float,
        default=30.0,
        help='Flight duration for aircraft transport'
    )
    
    parser.add_argument(
        '--unload_time',
        type=float,
        default=2.0,
        help='Time required for unloading cargo'
    )
    
    parser.add_argument(
        '--return_time',
        type=float,
        default=30.0,
        help='Return flight duration'
    )
    
    parser.add_argument(
        '--maintenance_time',
        type=float,
        default=10.0,
        help='Duration of maintenance phase'
    )
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.num_aircraft < 1:
        print("Error: num_aircraft must be >= 1", file=sys.stderr)
        sys.exit(1)
    
    # Create and run simulation
    simulation = AirfreightSimulation(
        duration=args.duration,
        num_aircraft=args.num_aircraft,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
        flight_time=args.flight_time,
        unload_time=args.unload_time,
        return_time=args.return_time,
        maintenance_time=args.maintenance_time
    )
    
    simulation.run()


if __name__ == '__main__':
    main()
