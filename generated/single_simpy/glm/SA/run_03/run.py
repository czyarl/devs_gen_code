import argparse
import sys
import json
import logging
import collections
import random
import simpy

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

class Pallet:
    """Represents a cargo pallet."""
    def __init__(self, pallet_id, gen_time, expiration_time):
        self.id = pallet_id
        self.gen_time = gen_time
        self.expiration_time = expiration_time
        self.assigned = False

class LoadingQueue:
    """Manages the queue of pallets waiting for aircraft."""
    def __init__(self, env):
        self.env = env
        self.queue = collections.deque()
        self.not_empty = env.event()  # Triggered when queue goes from empty to non-empty
        self.total_expired = 0

    def put(self, pallet):
        """Add a pallet to the queue and schedule expiration check."""
        self.queue.append(pallet)
        # Signal that queue is not empty
        if not self.not_empty.triggered:
            self.not_empty.succeed()
        
        self._log_queued(pallet)
        # Start the expiration monitor process for this pallet
        self.env.process(self._monitor_expiration(pallet))

    def get(self):
        """Remove and return the next pallet (FIFO)."""
        if not self.queue:
            return None
        pallet = self.queue.popleft()
        pallet.assigned = True
        
        # If queue becomes empty, reset the event for the next wait
        if not self.queue:
            self.not_empty = self.env.event()
            
        return pallet

    def _monitor_expiration(self, pallet):
        """Process that waits for the deadline and discards the pallet if still queued."""
        yield self.env.timeout(pallet.expiration_time - self.env.now)
        
        # Check if pallet is still in the queue
        # Note: 'in' check on deque is O(N), acceptable for this simulation scale
        if pallet in self.queue:
            self.queue.remove(pallet)
            self.total_expired += 1
            self._log_expired(pallet)

    def _log_queued(self, pallet):
        print(json.dumps({
            "time": self.env.now,
            "entity": "queue",
            "event": "pallet_queued",
            "payload": {
                "pallet_id": pallet.id,
                "queue_size": len(self.queue)
            }
        }))

    def _log_expired(self, pallet):
        print(json.dumps({
            "time": self.env.now,
            "entity": "queue",
            "event": "pallet_expired",
            "payload": {
                "pallet_id": pallet.id,
                "total_expired": self.total_expired
            }
        }))

class Aircraft:
    """Represents an aircraft performing transport cycles."""
    def __init__(self, env, aircraft_id, idle_store, args):
        self.env = env
        self.id = aircraft_id
        self.idle_store = idle_store
        self.args = args
        self.assignment_event = env.event()
        self.current_pallet = None
        self.process = env.process(self.run())

    def run(self):
        """Main operational cycle of the aircraft."""
        while True:
            # 1. Wait idle at facility (put self in idle store)
            yield self.idle_store.put(self)
            
            # Wait for coordinator to assign a pallet
            yield self.assignment_event
            pallet = self.current_pallet
            self.assignment_event = self.env.event() # Reset event for next trip
            
            # 2. Load (0s) -> Depart
            # According to requirements: "depart" happens when loading finishes (0s)
            print(json.dumps({
                "time": self.env.now,
                "entity": "aircraft",
                "event": "depart",
                "payload": {
                    "aircraft_id": self.id,
                    "pallet_id": pallet.id
                }
            }))

            # 3. Fly to destination
            yield self.env.timeout(self.args.flight_time)

            # 4. Unload cargo
            yield self.env.timeout(self.args.unload_time)
            
            # Destination Event: Pallet Delivered
            print(json.dumps({
                "time": self.env.now,
                "entity": "destination",
                "event": "pallet_delivered",
                "payload": {
                    "pallet_id": pallet.id,
                    "aircraft_id": self.id,
                    "latency": self.env.now - pallet.gen_time
                }
            }))

            # 5. Return to facility
            yield self.env.timeout(self.args.return_time)
            print(json.dumps({
                "time": self.env.now,
                "entity": "aircraft",
                "event": "return",
                "payload": {
                    "aircraft_id": self.id
                }
            }))

            # 6. Maintenance
            print(json.dumps({
                "time": self.env.now,
                "entity": "aircraft",
                "event": "maintenance_start",
                "payload": {
                    "aircraft_id": self.id
                }
            }))
            yield self.env.timeout(self.args.maintenance_time)
            print(json.dumps({
                "time": self.env.now,
                "entity": "aircraft",
                "event": "maintenance_end",
                "payload": {
                    "aircraft_id": self.id
                }
            }))

def facility_generator(env, queue, args):
    """Generates pallets at regular intervals."""
    pallet_id = 0
    while env.now < args.duration:
        # Generate pallet
        p = Pallet(
            pallet_id=pallet_id,
            gen_time=env.now,
            expiration_time=env.now + args.pallet_expiration_time
        )
        
        # Log generation
        print(json.dumps({
            "time": env.now,
            "entity": "facility",
            "event": "pallet_generated",
            "payload": {
                "pallet_id": p.id,
                "expiration_time": p.expiration_time
            }
        }))
        
        # Send to queue
        queue.put(p)
        
        pallet_id += 1
        yield env.timeout(args.pallet_interval)

def fleet_coordinator(env, queue, idle_store, args):
    """Assigns pallets to idle aircraft."""
    while True:
        # Wait for queue to have items
        if len(queue.queue) == 0:
            yield queue.not_empty
        
        # Wait for an aircraft to become available
        # We use get() which blocks until an item is available.
        # However, we must handle the race condition where the queue becomes empty
        # (due to expiration) while we were waiting for an aircraft.
        aircraft = yield idle_store.get()
        
        if len(queue.queue) > 0:
            # Assign pallet to aircraft
            pallet = queue.get()
            
            print(json.dumps({
                "time": env.now,
                "entity": "coordinator",
                "event": "assignment_created",
                "payload": {
                    "aircraft_id": aircraft.id,
                    "pallet_id": pallet.id
                }
            }))
            
            aircraft.current_pallet = pallet
            aircraft.assignment_event.succeed()
        else:
            # Queue became empty while waiting for aircraft (pallets expired)
            # Put aircraft back to idle store
            yield idle_store.put(aircraft)
            # Loop back to wait for queue

def main():
    parser = argparse.ArgumentParser(description="Airfreight Logistics Simulation")
    parser.add_argument("--duration", type=float, default=10000.0, help="Total simulation time")
    parser.add_argument("--num_aircraft", type=int, default=2, help="Number of aircraft")
    parser.add_argument("--pallet_interval", type=float, default=25.0, help="Interval between pallet generations")
    parser.add_argument("--pallet_expiration_time", type=float, default=150.0, help="Time window for pallet expiration")
    parser.add_argument("--flight_time", type=float, default=30.0, help="Flight duration")
    parser.add_argument("--unload_time", type=float, default=2.0, help="Unload time")
    parser.add_argument("--return_time", type=float, default=30.0, help="Return time")
    parser.add_argument("--maintenance_time", type=float, default=10.0, help="Maintenance time")
    
    args = parser.parse_args()
    
    logger.info(f"Starting simulation with duration: {args.duration}")
    
    env = simpy.Environment()
    
    # Initialize components
    queue = LoadingQueue(env)
    # Store to hold idle aircraft. Capacity is num_aircraft.
    idle_store = simpy.Store(env, capacity=args.num_aircraft)
    
    # Create Aircraft processes
    for i in range(args.num_aircraft):
        Aircraft(env, i, idle_store, args)
        
    # Start Facility and Coordinator processes
    env.process(facility_generator(env, queue, args))
    env.process(fleet_coordinator(env, queue, idle_store, args))
    
    # Run simulation
    env.run(until=args.duration)
    
    logger.info("Simulation finished.")

if __name__ == "__main__":
    main()