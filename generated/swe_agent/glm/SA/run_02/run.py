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
        """Flush stdout"""
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
        self.pallets: Dict[int, Pallet] = {}
        self.total_expired = 0
        self.expiration_events: Dict[int, simpy.Event] = {}
    
    def add_pallet(self, pallet: Pallet):
        """Add a pallet to the queue and schedule expiration check"""
        self.queue.append(pallet.id)
        self.pallets[pallet.id] = pallet
        
        # Log pallet queued
        self.logger.log(
            time=self.env.now,
            entity="queue",
            event="pallet_queued",
            payload={
                "pallet_id": pallet.id,
                "queue_size": len(self.queue)
            }
        )
        
        # Schedule expiration check
        time_until_expiration = pallet.expiration_time - self.env.now
        if time_until_expiration > 0:
            self.expiration_events[pallet.id] = self.env.timeout(time_until_expiration)
            self.env.process(self._check_expiration(pallet.id))
    
    def _check_expiration(self, pallet_id: int):
        """Check if pallet has expired and remove if so"""
        try:
            yield self.expiration_events[pallet_id]
            
            # Check if pallet is still in queue
            if pallet_id in self.pallets:
                self._remove_pallet(pallet_id, expired=True)
        except:
            # Pallet was assigned before expiration
            pass
    
    def _remove_pallet(self, pallet_id: int, expired: bool = False):
        """Remove a pallet from the queue"""
        if pallet_id in self.pallets:
            del self.pallets[pallet_id]
            if pallet_id in self.expiration_events:
                del self.expiration_events[pallet_id]
            
            # Remove from queue (rebuild deque without this item)
            self.queue = deque([pid for pid in self.queue if pid != pallet_id])
            
            if expired:
                self.total_expired += 1
                self.logger.log(
                    time=self.env.now,
                    entity="queue",
                    event="pallet_expired",
                    payload={
                        "pallet_id": pallet_id,
                        "total_expired": self.total_expired
                    }
                )
    
    def get_next_pallet(self) -> Optional[Pallet]:
        """Get the next pallet (FIFO)"""
        if self.queue:
            pallet_id = self.queue.popleft()
            pallet = self.pallets.pop(pallet_id, None)
            if pallet_id in self.expiration_events:
                del self.expiration_events[pallet_id]
            return pallet
        return None
    
    def has_pallets(self) -> bool:
        """Check if there are pallets in the queue"""
        return len(self.queue) > 0
    
    def get_queue_size(self) -> int:
        """Get current queue size"""
        return len(self.queue)


class Aircraft:
    """Represents an aircraft in the fleet"""
    
    # Aircraft states
    STATE_IDLE = "idle"
    STATE_FLYING = "flying"
    STATE_UNLOADING = "unloading"
    STATE_RETURNING = "returning"
    STATE_MAINTENANCE = "maintenance"
    
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
        self.state = self.STATE_IDLE
        self.current_pallet: Optional[Pallet] = None
    
    def is_idle(self) -> bool:
        """Check if aircraft is idle and available"""
        return self.state == self.STATE_IDLE
    
    def assign_pallet(self, pallet: Pallet):
        """Assign a pallet to this aircraft"""
        self.current_pallet = pallet
        self.state = self.STATE_FLYING
        self.env.process(self._transport_cycle())
    
    def _transport_cycle(self):
        """Execute the full transport cycle"""
        pallet = self.current_pallet
        
        # Log departure (loading is instantaneous)
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
        yield self.env.timeout(self.flight_time)
        
        # Unload cargo
        yield self.env.timeout(self.unload_time)
        
        # Log delivery
        latency = self.env.now - pallet.generation_time
        self.logger.log(
            time=self.env.now,
            entity="destination",
            event="pallet_delivered",
            payload={
                "pallet_id": pallet.id,
                "aircraft_id": self.id,
                "latency": latency
            }
        )
        
        # Return to facility
        self.state = self.STATE_RETURNING
        yield self.env.timeout(self.return_time)
        
        # Log return
        self.logger.log(
            time=self.env.now,
            entity="aircraft",
            event="return",
            payload={
                "aircraft_id": self.id
            }
        )
        
        # Maintenance
        self.state = self.STATE_MAINTENANCE
        self.logger.log(
            time=self.env.now,
            entity="aircraft",
            event="maintenance_start",
            payload={
                "aircraft_id": self.id
            }
        )
        yield self.env.timeout(self.maintenance_time)
        
        # Maintenance complete, back to idle
        self.logger.log(
            time=self.env.now,
            entity="aircraft",
            event="maintenance_end",
            payload={
                "aircraft_id": self.id
            }
        )
        
        self.state = self.STATE_IDLE
        self.current_pallet = None
        
        # Notify coordinator that we're available
        self.coordinator.notify_aircraft_available(self.id)


class FleetCoordinator:
    """Coordinates aircraft assignments"""
    
    def __init__(self, env: simpy.Environment, logger: EventLogger, 
                 loading_queue: LoadingQueue, aircraft_list: List[Aircraft]):
        self.env = env
        self.logger = logger
        self.loading_queue = loading_queue
        self.aircraft_list = aircraft_list
        self.aircraft_map = {ac.id: ac for ac in aircraft_list}
        self.env.process(self._coordinate())
    
    def notify_aircraft_available(self, aircraft_id: int):
        """Called when an aircraft becomes available"""
        # The coordinator process will check on next iteration
        pass
    
    def _coordinate(self):
        """Main coordination loop"""
        while True:
            # Check if there are pallets and available aircraft
            if self.loading_queue.has_pallets():
                for aircraft in self.aircraft_list:
                    if aircraft.is_idle():
                        pallet = self.loading_queue.get_next_pallet()
                        if pallet is not None:
                            # Log assignment
                            self.logger.log(
                                time=self.env.now,
                                entity="coordinator",
                                event="assignment_created",
                                payload={
                                    "aircraft_id": aircraft.id,
                                    "pallet_id": pallet.id
                                }
                            )
                            # Assign pallet to aircraft
                            aircraft.assign_pallet(pallet)
                            break
            
            # Wait a small amount before checking again
            yield self.env.timeout(0.1)


class Facility:
    """Generates cargo pallets"""
    
    def __init__(self, env: simpy.Environment, logger: EventLogger,
                 loading_queue: LoadingQueue, pallet_interval: float,
                 pallet_expiration_time: float, total_duration: float):
        self.env = env
        self.logger = logger
        self.loading_queue = loading_queue
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.total_duration = total_duration
        self.pallet_counter = 0
        self.env.process(self._generate_pallets())
    
    def _generate_pallets(self):
        """Generate pallets at regular intervals"""
        # Generate first pallet at time 0
        while True:
            self.pallet_counter += 1
            pallet_id = self.pallet_counter
            generation_time = self.env.now
            expiration_time = generation_time + self.pallet_expiration_time
            
            # Create pallet
            pallet = Pallet(pallet_id, generation_time, expiration_time)
            
            # Log generation
            self.logger.log(
                time=self.env.now,
                entity="facility",
                event="pallet_generated",
                payload={
                    "pallet_id": pallet_id,
                    "expiration_time": expiration_time
                }
            )
            
            # Add to loading queue
            self.loading_queue.add_pallet(pallet)
            
            # Check if we should continue generating
            if self.env.now >= self.total_duration:
                break
            
            # Wait for next generation
            yield self.env.timeout(self.pallet_interval)


class AirfreightSimulation:
    """Main simulation class"""
    
    def __init__(self, duration: float, num_aircraft: int, pallet_interval: float,
                 pallet_expiration_time: float, flight_time: float, unload_time: float,
                 return_time: float, maintenance_time: float):
        self.duration = duration
        self.num_aircraft = num_aircraft
        self.pallet_interval = pallet_interval
        self.pallet_expiration_time = pallet_expiration_time
        self.flight_time = flight_time
        self.unload_time = unload_time
        self.return_time = return_time
        self.maintenance_time = maintenance_time
        
        self.env = simpy.Environment()
        self.logger = EventLogger()
        
        # Create components
        self.loading_queue = LoadingQueue(self.env, self.logger)
        
        # Create aircraft
        self.aircraft_list = []
        for i in range(1, num_aircraft + 1):
            aircraft = Aircraft(
                aircraft_id=i,
                env=self.env,
                logger=self.logger,
                flight_time=flight_time,
                unload_time=unload_time,
                return_time=return_time,
                maintenance_time=maintenance_time,
                coordinator=None  # Will set after coordinator is created
            )
            self.aircraft_list.append(aircraft)
        
        # Create coordinator
        self.coordinator = FleetCoordinator(
            env=self.env,
            logger=self.logger,
            loading_queue=self.loading_queue,
            aircraft_list=self.aircraft_list
        )
        
        # Update aircraft with coordinator reference
        for aircraft in self.aircraft_list:
            aircraft.coordinator = self.coordinator
        
        # Create facility
        self.facility = Facility(
            env=self.env,
            logger=self.logger,
            loading_queue=self.loading_queue,
            pallet_interval=pallet_interval,
            pallet_expiration_time=pallet_expiration_time,
            total_duration=duration
        )
    
    def run(self):
        """Run the simulation"""
        logger.info(f"Starting simulation for {self.duration} time units")
        logger.info(f"Number of aircraft: {self.num_aircraft}")
        logger.info(f"Pallet interval: {self.pallet_interval}")
        logger.info(f"Pallet expiration time: {self.pallet_expiration_time}")
        
        # Handle zero or very small duration
        if self.duration > 0:
            self.env.run(until=self.duration)
        else:
            # For zero duration, just run the initial events
            self.env.run(until=0.001)
        
        logger.info(f"Simulation completed at time {self.env.now}")
        logger.info(f"Total events logged: {len(self.logger.events)}")
        
        # Flush output
        self.logger.flush()


def parse_arguments():
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
        help="Number of aircraft in the system (>= 1)"
    )
    
    parser.add_argument(
        "--pallet_interval",
        type=float,
        default=25.0,
        help="Time interval between pallet generations in time units"
    )
    
    parser.add_argument(
        "--pallet_expiration_time",
        type=float,
        default=150.0,
        help="Time window for pallet expiration (relative to generation)"
    )
    
    parser.add_argument(
        "--flight_time",
        type=float,
        default=30.0,
        help="Flight duration for aircraft transport in time units"
    )
    
    parser.add_argument(
        "--unload_time",
        type=float,
        default=2.0,
        help="Time required for unloading cargo at destination"
    )
    
    parser.add_argument(
        "--return_time",
        type=float,
        default=30.0,
        help="Return flight duration for aircraft"
    )
    
    parser.add_argument(
        "--maintenance_time",
        type=float,
        default=10.0,
        help="Duration of maintenance phase for aircraft"
    )
    
    return parser.parse_args()


def main():
    """Main entry point"""
    args = parse_arguments()
    
    # Validate arguments
    if args.num_aircraft < 1:
        logger.error("num_aircraft must be >= 1")
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


if __name__ == "__main__":
    main()