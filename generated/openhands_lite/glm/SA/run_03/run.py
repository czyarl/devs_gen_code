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
import simpy


class EventLogger:
    """Handles logging events to stdout in JSONL format"""
    
    def __init__(self):
        self.logger = logging.getLogger('simulation')
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        self.logger.addHandler(handler)
    
    def log_event(self, time: float, entity: str, event: str, payload: dict):
        """Log an event to stdout as JSONL"""
        event_obj = {
            "time": time,
            "entity": entity,
            "event": event,
            "payload": payload
        }
        print(json.dumps(event_obj))
    
    def debug(self, message: str):
        """Log debug message to stderr"""
        self.logger.debug(message)
    
    def info(self, message: str):
        """Log info message to stderr"""
        self.logger.info(message)


class Pallet:
    """Represents a cargo pallet"""
    
    def __init__(self, pallet_id: int, generation_time: float, expiration_time: float):
        self.id = pallet_id
        self.generation_time = generation_time
        self.expiration_time = expiration_time


class LoadingQueue:
    """Manages the loading queue with expiration monitoring"""
    
    def __init__(self, env: simpy.Environment, event_logger: EventLogger):
        self.env = env
        self.event_logger = event_logger
        self.queue = deque()
        self.pallets_in_queue: Dict[int, Pallet] = {}
        self.total_expired = 0
        self.expiration_process = env.process(self._monitor_expirations())
    
    def add_pallet(self, pallet: Pallet):
        """Add a pallet to the queue"""
        self.queue.append(pallet.id)
        self.pallets_in_queue[pallet.id] = pallet
        self.event_logger.log_event(
            self.env.now,
            "queue",
            "pallet_queued",
            {
                "pallet_id": pallet.id,
                "queue_size": len(self.queue)
            }
        )
    
    def get_next_pallet(self) -> Optional[Pallet]:
        """Get the next pallet (FIFO)"""
        if not self.queue:
            return None
        pallet_id = self.queue.popleft()
        pallet = self.pallets_in_queue.pop(pallet_id, None)
        return pallet
    
    def has_pallet(self) -> bool:
        """Check if queue has pallets"""
        return len(self.queue) > 0
    
    def _monitor_expirations(self):
        """Monitor and expire pallets that exceed their deadline"""
        while True:
            # Check for expired pallets
            current_time = self.env.now
            expired_ids = []
            
            for pallet_id, pallet in self.pallets_in_queue.items():
                if current_time >= pallet.expiration_time:
                    expired_ids.append(pallet_id)
            
            # Remove expired pallets
            for pallet_id in expired_ids:
                self._expire_pallet(pallet_id)
            
            # Check again after a short time
            yield self.env.timeout(0.1)
    
    def _expire_pallet(self, pallet_id: int):
        """Expire a pallet and remove from queue"""
        if pallet_id in self.pallets_in_queue:
            del self.pallets_in_queue[pallet_id]
            if pallet_id in self.queue:
                self.queue.remove(pallet_id)
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


class Aircraft:
    """Represents an aircraft in the fleet"""
    
    def __init__(self, aircraft_id: int, env: simpy.Environment, event_logger: EventLogger,
                 flight_time: float, unload_time: float, return_time: float, maintenance_time: float):
        self.id = aircraft_id
        self.env = env
        self.event_logger = event_logger
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.state = "idle"
        self.current_pallet: Optional[Pallet] = None
        self.assignment_event = env.event()
        self.process = env.process(self._run())
    
    def _run(self):
        """Main aircraft process"""
        while True:
            # Wait idle until assigned
            self.state = "idle"
            self.assignment_event = self.env.event()
            
            # Wait for assignment
            yield self.assignment_event
            
            # If assigned, perform transport cycle
            if self.current_pallet is not None:
                # Load (instantaneous)
                self.event_logger.log_event(
                    self.env.now,
                    "aircraft",
                    "depart",
                    {
                        "aircraft_id": self.id,
                        "pallet_id": self.current_pallet.id
                    }
                )
                
                # Fly to destination
                self.state = "in_flight"
                yield self.env.timeout(self.flight_time)
                
                # Unload cargo
                self.state = "unloading"
                yield self.env.timeout(self.unload_time)
                
                # Delivery happens here
                delivery_time = self.env.now
                latency = delivery_time - self.current_pallet.generation_time
                self.event_logger.log_event(
                    delivery_time,
                    "destination",
                    "pallet_delivered",
                    {
                        "pallet_id": self.current_pallet.id,
                        "aircraft_id": self.id,
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
                        "aircraft_id": self.id
                    }
                )
                
                # Maintenance
                self.state = "maintenance"
                self.event_logger.log_event(
                    self.env.now,
                    "aircraft",
                    "maintenance_start",
                    {
                        "aircraft_id": self.id
                    }
                )
                yield self.env.timeout(self.maintenance_time)
                
                self.event_logger.log_event(
                    self.env.now,
                    "aircraft",
                    "maintenance_end",
                    {
                        "aircraft_id": self.id
                    }
                )
                
                # Clear current pallet and go back to idle
                self.current_pallet = None
    
    def assign_pallet(self, pallet: Pallet):
        """Assign a pallet to this aircraft"""
        self.current_pallet = pallet
        # Trigger the assignment event
        if not self.assignment_event.triggered:
            self.assignment_event.succeed()
    
    def is_idle(self) -> bool:
        """Check if aircraft is idle"""
        return self.state == "idle" and self.current_pallet is None


class FleetCoordinator:
    """Coordinates aircraft assignments"""
    
    def __init__(self, env: simpy.Environment, event_logger: EventLogger,
                 loading_queue: LoadingQueue, aircraft_list: List[Aircraft]):
        self.env = env
        self.event_logger = event_logger
        self.loading_queue = loading_queue
        self.aircraft_list = aircraft_list
        self.process = env.process(self._coordinate())
    
    def _coordinate(self):
        """Main coordination process"""
        while True:
            # Check if we have pallets and idle aircraft
            if self.loading_queue.has_pallet():
                for aircraft in self.aircraft_list:
                    if aircraft.is_idle():
                        pallet = self.loading_queue.get_next_pallet()
                        if pallet is not None:
                            aircraft.assign_pallet(pallet)
                            self.event_logger.log_event(
                                self.env.now,
                                "coordinator",
                                "assignment_created",
                                {
                                    "aircraft_id": aircraft.id,
                                    "pallet_id": pallet.id
                                }
                            )
                            break
            
            # Check again after a short time
            yield self.env.timeout(0.1)


class Facility:
    """Generates pallets at regular intervals"""
    
    def __init__(self, env: simpy.Environment, event_logger: EventLogger,
                 loading_queue: LoadingQueue, pallet_interval: float, pallet_expiration_time: float):
        self.env = env
        self.event_logger = event_logger
        self.loading_queue = loading_queue
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.pallet_counter = 0
        self.process = env.process(self._generate_pallets())
    
    def _generate_pallets(self):
        """Generate pallets at regular intervals"""
        while True:
            self.pallet_counter += 1
            generation_time = self.env.now
            expiration_time = generation_time + self.pallet_expiration_time
            
            pallet = Pallet(self.pallet_counter, generation_time, expiration_time)
            
            self.event_logger.log_event(
                generation_time,
                "facility",
                "pallet_generated",
                {
                    "pallet_id": pallet.id,
                    "expiration_time": expiration_time
                }
            )
            
            self.loading_queue.add_pallet(pallet)
            
            # Wait for next pallet generation
            yield self.env.timeout(self.pallet_interval)


def run_simulation(duration: float, num_aircraft: int, pallet_interval: float,
                   pallet_expiration_time: float, flight_time: float, unload_time: float,
                   return_time: float, maintenance_time: float):
    """Run the airfreight logistics simulation"""
    
    # Setup
    env = simpy.Environment()
    event_logger = EventLogger()
    
    # Create components
    loading_queue = LoadingQueue(env, event_logger)
    
    aircraft_list = []
    for i in range(num_aircraft):
        aircraft = Aircraft(
            aircraft_id=i + 1,
            env=env,
            event_logger=event_logger,
            flight_time=flight_time,
            unload_time=unload_time,
            return_time=return_time,
            maintenance_time=maintenance_time
        )
        aircraft_list.append(aircraft)
    
    coordinator = FleetCoordinator(env, event_logger, loading_queue, aircraft_list)
    
    facility = Facility(
        env=env,
        event_logger=event_logger,
        loading_queue=loading_queue,
        pallet_interval=pallet_interval,
        pallet_expiration_time=pallet_expiration_time
    )
    
    # Run simulation
    event_logger.info(f"Starting simulation for {duration} time units")
    env.run(until=duration)
    event_logger.info(f"Simulation completed at time {env.now}")


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
        print("Error: num_aircraft must be >= 1", file=sys.stderr)
        sys.exit(1)
    
    # Run simulation
    run_simulation(
        duration=args.duration,
        num_aircraft=args.num_aircraft,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
        flight_time=args.flight_time,
        unload_time=args.unload_time,
        return_time=args.return_time,
        maintenance_time=args.maintenance_time
    )


if __name__ == "__main__":
    main()