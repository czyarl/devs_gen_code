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


class Pallet:
    """Represents a cargo pallet with ID and expiration time."""
    
    def __init__(self, pallet_id: int, generation_time: float, expiration_time: float):
        self.pallet_id = pallet_id
        self.generation_time = generation_time
        self.expiration_time = expiration_time


class AirfreightSimulation:
    """Main simulation class for airfreight logistics operations."""
    
    def __init__(self, env: simpy.Environment, config: dict):
        self.env = env
        self.config = config
        
        # Simulation state
        self.pallet_counter = 0
        self.expired_pallets_count = 0
        self.loading_queue = deque()
        
        # Aircraft state tracking
        self.aircraft_states = {}  # aircraft_id -> state
        self.aircraft_assignments = {}  # aircraft_id -> pallet
        
        # Initialize aircraft
        for i in range(config['num_aircraft']):
            aircraft_id = i + 1
            self.aircraft_states[aircraft_id] = 'idle'
            self.aircraft_assignments[aircraft_id] = None
            self.env.process(self.aircraft_operation(aircraft_id))
        
        # Start facility process
        self.env.process(self.facility_process())
        
        # Start coordinator process
        self.env.process(self.coordinator_process())
    
    def log_event(self, entity: str, event: str, payload: dict):
        """Log an event to stdout in JSONL format."""
        event_data = {
            "time": self.env.now,
            "entity": entity,
            "event": event,
            "payload": payload
        }
        print(json.dumps(event_data))
    
    def facility_process(self):
        """Generate pallets at regular intervals."""
        while True:
            # Generate new pallet
            self.pallet_counter += 1
            pallet_id = self.pallet_counter
            generation_time = self.env.now
            expiration_time = generation_time + self.config['pallet_expiration_time']
            
            pallet = Pallet(pallet_id, generation_time, expiration_time)
            
            # Log pallet generation
            self.log_event(
                "facility",
                "pallet_generated",
                {
                    "pallet_id": pallet_id,
                    "expiration_time": expiration_time
                }
            )
            
            # Add to loading queue
            self.loading_queue.append(pallet)
            
            # Log pallet queued
            self.log_event(
                "queue",
                "pallet_queued",
                {
                    "pallet_id": pallet_id,
                    "queue_size": len(self.loading_queue)
                }
            )
            
            # Wait for next pallet generation
            yield self.env.timeout(self.config['pallet_interval'])
    
    def coordinator_process(self):
        """Assign pallets to idle aircraft and monitor expiration."""
        while True:
            current_time = self.env.now
            
            # Check for expired pallets
            expired_pallets = []
            for pallet in self.loading_queue:
                if pallet.expiration_time <= current_time:
                    expired_pallets.append(pallet)
            
            # Remove expired pallets
            for pallet in expired_pallets:
                self.loading_queue.remove(pallet)
                self.expired_pallets_count += 1
                
                # Log pallet expiration
                self.log_event(
                    "queue",
                    "pallet_expired",
                    {
                        "pallet_id": pallet.pallet_id,
                        "total_expired": self.expired_pallets_count
                    }
                )
            
            # Assign pallets to idle aircraft
            if self.loading_queue:
                for aircraft_id, state in self.aircraft_states.items():
                    if state == 'idle' and self.loading_queue:
                        # Assign pallet to aircraft
                        pallet = self.loading_queue.popleft()
                        self.aircraft_assignments[aircraft_id] = pallet
                        
                        # Log assignment
                        self.log_event(
                            "coordinator",
                            "assignment_created",
                            {
                                "aircraft_id": aircraft_id,
                                "pallet_id": pallet.pallet_id
                            }
                        )
            
            # Wait a small time step before checking again
            yield self.env.timeout(0.1)
    
    def aircraft_operation(self, aircraft_id: int):
        """Aircraft operation process."""
        while True:
            # Wait for assignment (idle state)
            while self.aircraft_assignments[aircraft_id] is None:
                yield self.env.timeout(0.1)
            
            pallet = self.aircraft_assignments[aircraft_id]
            
            # Update state
            self.aircraft_states[aircraft_id] = 'loading'
            
            # Load cargo (instantaneous)
            self.log_event(
                "aircraft",
                "depart",
                {
                    "aircraft_id": aircraft_id,
                    "pallet_id": pallet.pallet_id
                }
            )
            
            # Fly to destination
            self.aircraft_states[aircraft_id] = 'in-flight'
            yield self.env.timeout(self.config['flight_time'])
            
            # Unload cargo
            self.aircraft_states[aircraft_id] = 'unloading'
            yield self.env.timeout(self.config['unload_time'])
            
            # Log delivery
            self.log_event(
                "destination",
                "pallet_delivered",
                {
                    "pallet_id": pallet.pallet_id,
                    "aircraft_id": aircraft_id,
                    "latency": self.env.now - pallet.generation_time
                }
            )
            
            # Return to facility
            self.aircraft_states[aircraft_id] = 'returning'
            yield self.env.timeout(self.config['return_time'])
            
            # Log return
            self.log_event(
                "aircraft",
                "return",
                {
                    "aircraft_id": aircraft_id
                }
            )
            
            # Maintenance
            self.aircraft_states[aircraft_id] = 'maintenance'
            self.log_event(
                "aircraft",
                "maintenance_start",
                {
                    "aircraft_id": aircraft_id
                }
            )
            yield self.env.timeout(self.config['maintenance_time'])
            
            # Log maintenance end
            self.log_event(
                "aircraft",
                "maintenance_end",
                {
                    "aircraft_id": aircraft_id
                }
            )
            
            # Return to idle
            self.aircraft_states[aircraft_id] = 'idle'
            self.aircraft_assignments[aircraft_id] = None


def main():
    """Main entry point for the simulation."""
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
        logger.error("num_aircraft must be >= 1")
        sys.exit(1)
    
    # Create configuration
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
    
    logger.info(f"Starting simulation with config: {config}")
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create and run simulation
    simulation = AirfreightSimulation(env, config)
    env.run(until=config['duration'])
    
    logger.info("Simulation completed")


if __name__ == '__main__':
    main()