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


class SimulationLogger:
    """Handles logging events to stdout (JSONL) and stderr (debug)"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        self.logger.addHandler(handler)
    
    def log_event(self, time: float, entity: str, event: str, payload: dict):
        """Log an event to stdout as JSONL"""
        event_obj = {
            "time": time,
            "entity": entity,
            "event": event,
            "payload": payload
        }
        print(json.dumps(event_obj), file=sys.stdout, flush=True)
    
    def debug(self, message: str):
        """Log debug message to stderr"""
        self.logger.info(message)


class Pallet:
    """Represents a cargo pallet"""
    
    def __init__(self, pallet_id: int, generation_time: float, expiration_time: float):
        self.pallet_id = pallet_id
        self.generation_time = generation_time
        self.expiration_time = expiration_time


class LoadingQueue:
    """Manages the loading queue with expiration monitoring"""
    
    def __init__(self, env: simpy.Environment, logger: SimulationLogger):
        self.env = env
        self.logger = logger
        self.queue: deque[Pallet] = deque()
        self.total_expired = 0
        self.expiration_process = env.process(self._monitor_expirations())
    
    def add_pallet(self, pallet: Pallet):
        """Add a pallet to the queue"""
        self.queue.append(pallet)
        self.logger.log_event(
            self.env.now,
            "queue",
            "pallet_queued",
            {
                "pallet_id": pallet.pallet_id,
                "queue_size": len(self.queue)
            }
        )
    
    def get_next_pallet(self) -> Optional[Pallet]:
        """Get the next pallet (FIFO)"""
        if self.queue:
            return self.queue.popleft()
        return None
    
    def _monitor_expirations(self):
        """Monitor and expire pallets that exceed their deadline"""
        while True:
            # Check if any pallet has expired
            while self.queue and self.env.now >= self.queue[0].expiration_time:
                expired_pallet = self.queue.popleft()
                self.total_expired += 1
                self.logger.log_event(
                    self.env.now,
                    "queue",
                    "pallet_expired",
                    {
                        "pallet_id": expired_pallet.pallet_id,
                        "total_expired": self.total_expired
                    }
                )
                self.logger.debug(f"Pallet {expired_pallet.pallet_id} expired at time {self.env.now}")
            
            # Wait a small time before checking again
            yield self.env.timeout(0.1)


class Aircraft:
    """Represents an aircraft in the fleet"""
    
    def __init__(self, aircraft_id: int, env: simpy.Environment, logger: SimulationLogger,
                 flight_time: float, unload_time: float, return_time: float, maintenance_time: float):
        self.aircraft_id = aircraft_id
        self.env = env
        self.logger = logger
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        self.state = "idle"  # idle, in_flight, unloading, returning, maintenance
        self.current_pallet: Optional[Pallet] = None
        self.assignment_event = simpy.Event(env)
        self.process = env.process(self._run_cycle())
    
    def assign_pallet(self, pallet: Pallet):
        """Assign a pallet to this aircraft"""
        self.current_pallet = pallet
        self.assignment_event.succeed()
    
    def _run_cycle(self):
        """Main aircraft operation cycle"""
        while True:
            # Wait idle until assigned
            self.state = "idle"
            self.assignment_event = simpy.Event(self.env)
            yield self.assignment_event  # Wait for assignment
            
            # If we have a pallet, start the transport cycle
            if self.current_pallet:
                # Load (instantaneous, 0s)
                self.logger.log_event(
                    self.env.now,
                    "aircraft",
                    "depart",
                    {
                        "aircraft_id": self.aircraft_id,
                        "pallet_id": self.current_pallet.pallet_id
                    }
                )
                self.logger.debug(f"Aircraft {self.aircraft_id} departed with pallet {self.current_pallet.pallet_id}")
                
                # Fly to destination
                self.state = "in_flight"
                yield self.env.timeout(self.flight_time)
                
                # Unload cargo
                self.state = "unloading"
                yield self.env.timeout(self.unload_time)
                
                # Delivery happens here
                delivery_time = self.env.now
                latency = delivery_time - self.current_pallet.generation_time
                self.logger.log_event(
                    self.env.now,
                    "destination",
                    "pallet_delivered",
                    {
                        "pallet_id": self.current_pallet.pallet_id,
                        "aircraft_id": self.aircraft_id,
                        "latency": latency
                    }
                )
                self.logger.debug(f"Pallet {self.current_pallet.pallet_id} delivered by aircraft {self.aircraft_id}, latency: {latency}")
                
                # Return to facility
                self.state = "returning"
                yield self.env.timeout(self.return_time)
                
                self.logger.log_event(
                    self.env.now,
                    "aircraft",
                    "return",
                    {
                        "aircraft_id": self.aircraft_id
                    }
                )
                self.logger.debug(f"Aircraft {self.aircraft_id} returned to facility")
                
                # Maintenance
                self.state = "maintenance"
                self.logger.log_event(
                    self.env.now,
                    "aircraft",
                    "maintenance_start",
                    {
                        "aircraft_id": self.aircraft_id
                    }
                )
                yield self.env.timeout(self.maintenance_time)
                
                self.logger.log_event(
                    self.env.now,
                    "aircraft",
                    "maintenance_end",
                    {
                        "aircraft_id": self.aircraft_id
                    }
                )
                self.logger.debug(f"Aircraft {self.aircraft_id} completed maintenance")
                
                # Clear current pallet and go back to idle
                self.current_pallet = None


class FleetCoordinator:
    """Coordinates aircraft assignments"""
    
    def __init__(self, env: simpy.Environment, logger: SimulationLogger, 
                 loading_queue: LoadingQueue, aircraft_list: List[Aircraft]):
        self.env = env
        self.logger = logger
        self.loading_queue = loading_queue
        self.aircraft_list = aircraft_list
        self.process = env.process(self._coordinate())
    
    def _coordinate(self):
        """Monitor and assign pallets to idle aircraft"""
        while True:
            # Check if there are pallets in queue and idle aircraft
            if self.loading_queue.queue:
                for aircraft in self.aircraft_list:
                    if aircraft.state == "idle" and aircraft.current_pallet is None:
                        # Assign next pallet to this aircraft
                        pallet = self.loading_queue.get_next_pallet()
                        if pallet:
                            aircraft.assign_pallet(pallet)
                            self.logger.log_event(
                                self.env.now,
                                "coordinator",
                                "assignment_created",
                                {
                                    "aircraft_id": aircraft.aircraft_id,
                                    "pallet_id": pallet.pallet_id
                                }
                            )
                            self.logger.debug(f"Assigned pallet {pallet.pallet_id} to aircraft {aircraft.aircraft_id}")
                            break  # Only assign one pallet per check
            
            # Wait a short time before checking again
            yield self.env.timeout(0.1)


class Facility:
    """Generates pallets at regular intervals"""
    
    def __init__(self, env: simpy.Environment, logger: SimulationLogger,
                 loading_queue: LoadingQueue, pallet_interval: float, pallet_expiration_time: float):
        self.env = env
        self.logger = logger
        self.loading_queue = loading_queue
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.pallet_counter = 0
        self.process = env.process(self._generate_pallets())
    
    def _generate_pallets(self):
        """Generate pallets at regular intervals"""
        while True:
            self.pallet_counter += 1
            pallet_id = self.pallet_counter
            generation_time = self.env.now
            expiration_time = generation_time + self.pallet_expiration_time
            
            pallet = Pallet(pallet_id, generation_time, expiration_time)
            
            self.logger.log_event(
                self.env.now,
                "facility",
                "pallet_generated",
                {
                    "pallet_id": pallet_id,
                    "expiration_time": expiration_time
                }
            )
            self.logger.debug(f"Generated pallet {pallet_id} at time {generation_time}, expires at {expiration_time}")
            
            # Add to loading queue
            self.loading_queue.add_pallet(pallet)
            
            # Wait for next generation
            yield self.env.timeout(self.pallet_interval)


def run_simulation(duration: float, num_aircraft: int, pallet_interval: float,
                   pallet_expiration_time: float, flight_time: float, unload_time: float,
                   return_time: float, maintenance_time: float):
    """Run the airfreight logistics simulation"""
    
    # Setup
    env = simpy.Environment()
    logger = SimulationLogger()
    
    logger.debug(f"Starting simulation with duration={duration}, num_aircraft={num_aircraft}")
    logger.debug(f"Parameters: pallet_interval={pallet_interval}, pallet_expiration_time={pallet_expiration_time}")
    logger.debug(f"Flight parameters: flight_time={flight_time}, unload_time={unload_time}, return_time={return_time}, maintenance_time={maintenance_time}")
    
    # Create entities
    loading_queue = LoadingQueue(env, logger)
    
    aircraft_list = []
    for i in range(num_aircraft):
        aircraft = Aircraft(
            aircraft_id=i + 1,
            env=env,
            logger=logger,
            flight_time=flight_time,
            unload_time=unload_time,
            return_time=return_time,
            maintenance_time=maintenance_time
        )
        aircraft_list.append(aircraft)
    
    coordinator = FleetCoordinator(env, logger, loading_queue, aircraft_list)
    
    facility = Facility(
        env=env,
        logger=logger,
        loading_queue=loading_queue,
        pallet_interval=pallet_interval,
        pallet_expiration_time=pallet_expiration_time
    )
    
    # Run simulation
    logger.debug(f"Simulation running until time {duration}")
    env.run(until=duration)
    logger.debug(f"Simulation completed at time {env.now}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Airfreight Logistics Operations Simulation')
    
    parser.add_argument('--duration', type=float, default=10000.0,
                        help='Total simulation time in time units (default: 10000.0)')
    parser.add_argument('--num_aircraft', type=int, default=2,
                        help='Number of aircraft in the system (default: 2)')
    parser.add_argument('--pallet_interval', type=float, default=25.0,
                        help='Time interval between pallet generations (default: 25.0)')
    parser.add_argument('--pallet_expiration_time', type=float, default=150.0,
                        help='Time window for pallet expiration (default: 150.0)')
    parser.add_argument('--flight_time', type=float, default=30.0,
                        help='Flight duration for aircraft transport (default: 30.0)')
    parser.add_argument('--unload_time', type=float, default=2.0,
                        help='Time required for unloading cargo (default: 2.0)')
    parser.add_argument('--return_time', type=float, default=30.0,
                        help='Return flight duration (default: 30.0)')
    parser.add_argument('--maintenance_time', type=float, default=10.0,
                        help='Duration of maintenance phase (default: 10.0)')
    
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
        duration=args.duration,
        num_aircraft=args.num_aircraft,
        pallet_interval=args.pallet_interval,
        pallet_expiration_time=args.pallet_expiration_time,
        flight_time=args.flight_time,
        unload_time=args.unload_time,
        return_time=args.return_time,
        maintenance_time=args.maintenance_time
    )


if __name__ == '__main__':
    main()