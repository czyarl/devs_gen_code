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
    """Handles logging events to stdout (JSONL) and stderr (debug)"""
    
    def __init__(self):
        self.logger = logging.getLogger('simulation')
        self.logger.setLevel(logging.DEBUG)
        handler = logging.StreamHandler(sys.stderr)
        handler.setLevel(logging.DEBUG)
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


class Pallet:
    """Represents a cargo pallet"""
    
    def __init__(self, pallet_id, generation_time, expiration_time):
        self.pallet_id = pallet_id
        self.generation_time = generation_time
        self.expiration_time = expiration_time


class LoadingQueue:
    """Manages the loading queue with expiration monitoring"""
    
    def __init__(self, env, event_logger):
        self.env = env
        self.event_logger = event_logger
        self.queue = deque()
        self.pallet_info = {}  # pallet_id -> (pallet, queue_time)
        self.total_expired = 0
        self.expiration_processes = {}  # pallet_id -> process
    
    def add_pallet(self, pallet):
        """Add a pallet to the queue and schedule expiration check"""
        self.queue.append(pallet.pallet_id)
        self.pallet_info[pallet.pallet_id] = (pallet, self.env.now)
        
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
        time_until_expiration = pallet.expiration_time - self.env.now
        if time_until_expiration > 0:
            process = self.env.process(self._monitor_expiration(pallet))
            self.expiration_processes[pallet.pallet_id] = process
    
    def _monitor_expiration(self, pallet):
        """Monitor pallet for expiration"""
        time_until_expiration = pallet.expiration_time - self.env.now
        if time_until_expiration > 0:
            yield self.env.timeout(time_until_expiration)
        
        # Check if pallet is still in queue
        if pallet.pallet_id in self.pallet_info:
            self._expire_pallet(pallet.pallet_id)
    
    def _expire_pallet(self, pallet_id):
        """Remove expired pallet from queue"""
        if pallet_id in self.pallet_info:
            del self.pallet_info[pallet_id]
            if pallet_id in self.expiration_processes:
                del self.expiration_processes[pallet_id]
            
            # Remove from queue (maintain order)
            try:
                self.queue.remove(pallet_id)
            except ValueError:
                pass
            
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
    
    def get_next_pallet(self):
        """Get next pallet (FIFO) or None if queue is empty"""
        if not self.queue:
            return None
        
        pallet_id = self.queue.popleft()
        pallet, queue_time = self.pallet_info.pop(pallet_id, (None, None))
        
        # Cancel expiration process if exists
        if pallet_id in self.expiration_processes:
            self.expiration_processes[pallet_id].interrupt()
            del self.expiration_processes[pallet_id]
        
        return pallet
    
    def has_pallets(self):
        """Check if queue has pallets"""
        return len(self.queue) > 0


class Aircraft:
    """Represents an aircraft in the fleet"""
    
    def __init__(self, aircraft_id, env, event_logger, coordinator, config):
        self.aircraft_id = aircraft_id
        self.env = env
        self.event_logger = event_logger
        self.coordinator = coordinator
        self.config = config
        self.state = "idle"  # idle, in_flight, unloading, returning, maintenance
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
            
            # Load (instantaneous, 0s)
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
            self.state = "in_flight"
            yield self.env.timeout(self.config['flight_time'])
            
            # Unload cargo
            self.state = "unloading"
            yield self.env.timeout(self.config['unload_time'])
            
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
            yield self.env.timeout(self.config['return_time'])
            
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
            
            yield self.env.timeout(self.config['maintenance_time'])
            
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
    
    def __init__(self, env, event_logger, loading_queue, num_aircraft):
        self.env = env
        self.event_logger = event_logger
        self.loading_queue = loading_queue
        self.num_aircraft = num_aircraft
        self.assignment_requests = []  # List of (aircraft_id, event)
        self.aircraft_status = {}  # aircraft_id -> status
    
    def register_aircraft(self, aircraft_id):
        """Register an aircraft with the coordinator"""
        self.aircraft_status[aircraft_id] = "idle"
    
    def get_assignment(self, aircraft_id):
        """Aircraft requests assignment"""
        event = self.env.event()
        self.assignment_requests.append((aircraft_id, event))
        self.aircraft_status[aircraft_id] = "waiting"
        self._try_assign()
        return event
    
    def _try_assign(self):
        """Try to assign pallets to waiting aircraft"""
        while (self.assignment_requests and 
               self.loading_queue.has_pallets()):
            
            aircraft_id, event = self.assignment_requests.pop(0)
            pallet = self.loading_queue.get_next_pallet()
            
            if pallet is not None:
                self.aircraft_status[aircraft_id] = "assigned"
                self.event_logger.log_event(
                    self.env.now,
                    "coordinator",
                    "assignment_created",
                    {
                        "aircraft_id": aircraft_id,
                        "pallet_id": pallet.pallet_id
                    }
                )
                event.succeed(pallet)
            else:
                # Put back the request
                self.assignment_requests.insert(0, (aircraft_id, event))
                break
    
    def check_assignments(self):
        """Called when new pallet arrives"""
        self._try_assign()


class Facility:
    """Generates cargo pallets at regular intervals"""
    
    def __init__(self, env, event_logger, loading_queue, coordinator, config):
        self.env = env
        self.event_logger = event_logger
        self.loading_queue = loading_queue
        self.coordinator = coordinator
        self.config = config
        self.pallet_counter = 0
    
    def run(self):
        """Generate pallets at regular intervals"""
        while True:
            # Check if we should continue generating
            if self.env.now >= self.config['duration']:
                break
            
            # Generate new pallet
            self.pallet_counter += 1
            pallet_id = self.pallet_counter
            generation_time = self.env.now
            expiration_time = generation_time + self.config['pallet_expiration_time']
            
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
            
            # Add to loading queue
            self.loading_queue.add_pallet(pallet)
            
            # Notify coordinator to check for assignments
            self.coordinator.check_assignments()
            
            # Wait for next pallet generation
            yield self.env.timeout(self.config['pallet_interval'])


class AirfreightSimulation:
    """Main simulation class"""
    
    def __init__(self, config):
        self.config = config
        self.env = simpy.Environment()
        self.event_logger = EventLogger()
        
        # Create components
        self.loading_queue = LoadingQueue(self.env, self.event_logger)
        self.coordinator = FleetCoordinator(
            self.env, self.event_logger, self.loading_queue, config['num_aircraft']
        )
        self.facility = Facility(
            self.env, self.event_logger, self.loading_queue, self.coordinator, config
        )
        
        # Create aircraft
        self.aircraft = []
        for i in range(1, config['num_aircraft'] + 1):
            aircraft = Aircraft(i, self.env, self.event_logger, self.coordinator, config)
            self.coordinator.register_aircraft(i)
            self.aircraft.append(aircraft)
    
    def run(self):
        """Run the simulation"""
        self.event_logger.debug(f"Starting simulation with duration {self.config['duration']}")
        self.event_logger.debug(f"Number of aircraft: {self.config['num_aircraft']}")
        self.event_logger.debug(f"Pallet interval: {self.config['pallet_interval']}")
        self.event_logger.debug(f"Pallet expiration time: {self.config['pallet_expiration_time']}")
        
        # Start processes
        self.env.process(self.facility.run())
        for aircraft in self.aircraft:
            self.env.process(aircraft.run())
        
        # Run simulation
        self.env.run(until=self.config['duration'])
        
        self.event_logger.debug(f"Simulation completed at time {self.env.now}")


def parse_arguments():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description='Airfreight Logistics Operations Simulation'
    )
    
    parser.add_argument(
        '--duration',
        type=float,
        default=10000.0,
        help='Total simulation time in time units (default: 10000.0)'
    )
    
    parser.add_argument(
        '--num_aircraft',
        type=int,
        default=2,
        help='Number of aircraft in the system (default: 2)'
    )
    
    parser.add_argument(
        '--pallet_interval',
        type=float,
        default=25.0,
        help='Time interval between pallet generations (default: 25.0)'
    )
    
    parser.add_argument(
        '--pallet_expiration_time',
        type=float,
        default=150.0,
        help='Time window for pallet expiration (default: 150.0)'
    )
    
    parser.add_argument(
        '--flight_time',
        type=float,
        default=30.0,
        help='Flight duration for aircraft transport (default: 30.0)'
    )
    
    parser.add_argument(
        '--unload_time',
        type=float,
        default=2.0,
        help='Time required for unloading cargo (default: 2.0)'
    )
    
    parser.add_argument(
        '--return_time',
        type=float,
        default=30.0,
        help='Return flight duration (default: 30.0)'
    )
    
    parser.add_argument(
        '--maintenance_time',
        type=float,
        default=10.0,
        help='Duration of maintenance phase (default: 10.0)'
    )
    
    return parser.parse_args()


def main():
    """Main entry point"""
    args = parse_arguments()
    
    # Build configuration
    config = {
        'duration': args.duration,
        'num_aircraft': args.num_aircraft,
        'pallet_interval': args.pallet_interval,
        'pallet_expiration_time': args.pallet_expiration_time,
        'flight_time': args.flight_time,
        'unload_time': args.unload_time,
        'return_time': args.return_time,
        'maintenance_time': args.maintenance_time
    }
    
    # Validate arguments
    if config['num_aircraft'] < 1:
        print("Error: num_aircraft must be >= 1", file=sys.stderr)
        sys.exit(1)
    
    # Run simulation
    simulation = AirfreightSimulation(config)
    simulation.run()


if __name__ == '__main__':
    main()
