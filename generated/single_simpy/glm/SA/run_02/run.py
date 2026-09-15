import argparse
import json
import logging
import sys
import time
import simpy
from collections import deque

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

class EventLogger:
    """Helper class to manage JSONL output to stdout."""
    def __init__(self):
        pass

    def log(self, time, entity, event, payload):
        record = {
            "time": round(time, 6),
            "entity": entity,
            "event": event,
            "payload": payload
        }
        print(json.dumps(record))
        sys.stdout.flush()

class Pallet:
    def __init__(self, pallet_id, generation_time, expiration_time):
        self.id = pallet_id
        self.generation_time = generation_time
        self.expiration_time = expiration_time

class LoadingQueue:
    def __init__(self, env, event_logger):
        self.env = env
        self.logger = event_logger
        self.queue = deque()
        self.total_expired = 0
        
    def add_pallet(self, pallet):
        self.queue.append(pallet)
        self.logger.log(self.env.now, "queue", "pallet_queued", {
            "pallet_id": pallet.id,
            "queue_size": len(self.queue)
        })
        # Schedule expiration check
        time_to_expire = pallet.expiration_time - self.env.now
        if time_to_expire > 0:
            self.env.process(self._expire_pallet(pallet, time_to_expire))
        else:
            # Should not happen if logic is correct, but handle edge case
            self._remove_and_log_expire(pallet)

    def _expire_pallet(self, pallet, delay):
        yield self.env.timeout(delay)
        # Check if pallet is still in queue (might have been assigned)
        if pallet in self.queue:
            self._remove_and_log_expire(pallet)

    def _remove_and_log_expire(self, pallet):
        try:
            self.queue.remove(pallet)
            self.total_expired += 1
            self.logger.log(self.env.now, "queue", "pallet_expired", {
                "pallet_id": pallet.id,
                "total_expired": self.total_expired
            })
        except ValueError:
            # Pallet already removed (assigned)
            pass

    def get_next_pallet(self):
        if self.queue:
            return self.queue.popleft()
        return None

    def has_pallets(self):
        return len(self.queue) > 0

class Aircraft:
    def __init__(self, env, aircraft_id, event_logger, config, coordinator):
        self.env = env
        self.id = aircraft_id
        self.logger = event_logger
        self.config = config
        self.coordinator = coordinator
        self.state = "idle" # idle, flying, unloading, returning, maintenance
        self.current_pallet = None
        
        # Start the aircraft process
        self.env.process(self.run())

    def run(self):
        while True:
            # 1. Wait idle at facility
            self.state = "idle"
            # Signal coordinator that we are idle
            self.coordinator.notify_idle(self)
            
            # Wait for assignment
            # This is a blocking wait handled by the coordinator triggering an event
            yield self.coordinator.get_assignment_event(self.id)

            # 2. Load assigned cargo (Instantaneous: 0s)
            # The coordinator sets self.current_pallet before triggering the event
            pallet = self.current_pallet
            
            self.logger.log(self.env.now, "aircraft", "depart", {
                "aircraft_id": self.id,
                "pallet_id": pallet.id
            })

            # 3. Fly to destination
            self.state = "flying"
            yield self.env.timeout(self.config['flight_time'])

            # 4. Unload cargo
            self.state = "unloading"
            yield self.env.timeout(self.config['unload_time'])
            
            # Delivery happens here
            latency = self.env.now - pallet.generation_time
            self.logger.log(self.env.now, "destination", "pallet_delivered", {
                "pallet_id": pallet.id,
                "aircraft_id": self.id,
                "latency": round(latency, 6)
            })
            self.current_pallet = None

            # 5. Return to facility
            self.state = "returning"
            yield self.env.timeout(self.config['return_time'])
            
            self.logger.log(self.env.now, "aircraft", "return", {
                "aircraft_id": self.id
            })

            # 6. Maintenance
            self.state = "maintenance"
            self.logger.log(self.env.now, "aircraft", "maintenance_start", {
                "aircraft_id": self.id
            })
            yield self.env.timeout(self.config['maintenance_time'])
            self.logger.log(self.env.now, "aircraft", "maintenance_end", {
                "aircraft_id": self.id
            })

class Coordinator:
    def __init__(self, env, event_logger, loading_queue, num_aircraft):
        self.env = env
        self.logger = event_logger
        self.loading_queue = loading_queue
        self.aircraft_events = {} # Map aircraft_id -> simpy.Event
        
        # Initialize events for all aircraft
        for i in range(num_aircraft):
            self.aircraft_events[i] = simpy.Event(env)

    def notify_idle(self, aircraft):
        # Reset the event for this aircraft so it can be triggered again
        self.aircraft_events[aircraft.id] = simpy.Event(self.env)
        # Trigger assignment logic
        self.env.process(self.assign_logic())

    def get_assignment_event(self, aircraft_id):
        return self.aircraft_events[aircraft_id]

    def assign_logic(self):
        # Check if we have pallets and idle aircraft
        # Note: This logic runs whenever an aircraft becomes idle or a pallet is generated.
        # However, to avoid race conditions or multiple triggers, we check state.
        
        # We need to find an aircraft that is waiting (event is pending/not triggered)
        # and a pallet in queue.
        
        if self.loading_queue.has_pallets():
            for aid, evt in self.aircraft_events.items():
                if not evt.triggered: # Aircraft is idle and waiting
                    pallet = self.loading_queue.get_next_pallet()
                    if pallet:
                        # Assign
                        self.logger.log(self.env.now, "coordinator", "assignment_created", {
                            "aircraft_id": aid,
                            "pallet_id": pallet.id
                        })
                        
                        # We need to pass the pallet to the aircraft.
                        # Since we don't have a direct reference to the Aircraft object here easily 
                        # without storing it, we can rely on the fact that the Aircraft process 
                        # is waiting on this specific event.
                        # But how does the aircraft know WHICH pallet?
                        # In SimPy, Events are just signals. We need a shared store or a way to pass data.
                        
                        # Let's modify the Aircraft to look up its assignment from the Coordinator 
                        # or pass the data via a shared dictionary.
                        
                        # Let's use a shared dictionary for assignments.
                        self.current_assignment = {aid: pallet}
                        evt.succeed() # Trigger the aircraft
                        return # Only assign one at a time per trigger to be safe, or loop

def run_simulation(args):
    env = simpy.Environment()
    event_logger = EventLogger()
    
    # Configuration dictionary
    config = {
        'flight_time': args.flight_time,
        'unload_time': args.unload_time,
        'return_time': args.return_time,
        'maintenance_time': args.maintenance_time
    }
    
    loading_queue = LoadingQueue(env, event_logger)
    coordinator = Coordinator(env, event_logger, loading_queue, args.num_aircraft)
    
    # Create Aircraft
    aircrafts = []
    for i in range(args.num_aircraft):
        ac = Aircraft(env, i, event_logger, config, coordinator)
        aircrafts.append(ac)
    
    # Patch Coordinator to have access to aircraft objects if needed, 
    # or simpler: The coordinator stores the assignment in a temp dict that the aircraft reads.
    # Let's refine the assignment mechanism.
    # The Aircraft process yields on `coordinator.get_assignment_event(self.id)`.
    # The Coordinator logic needs to set `aircraft.current_pallet` before triggering.
    
    # Let's redefine the Coordinator logic slightly to integrate better.
    # We'll pass the list of aircrafts to the coordinator so it can set the pallet.
    coordinator.aircrafts = aircrafts

    # Redefine assign_logic to use the aircraft list
    def assign_logic_process():
        while True:
            # Wait for a change: either a pallet arrives or an aircraft becomes idle.
            # We can use a condition or simply check whenever these events happen.
            # To keep it simple and event-driven, we call this check explicitly.
            
            if loading_queue.has_pallets():
                for ac in aircrafts:
                    if ac.state == "idle" and not coordinator.aircraft_events[ac.id].triggered:
                        pallet = loading_queue.get_next_pallet()
                        if pallet:
                            event_logger.log(env.now, "coordinator", "assignment_created", {
                                "aircraft_id": ac.id,
                                "pallet_id": pallet.id
                            })
                            ac.current_pallet = pallet
                            coordinator.aircraft_events[ac.id].succeed()
                            break # One assignment per step to avoid complexity
            
            # Wait for next event trigger (either new pallet or aircraft idle)
            # We can create a generic event that gets triggered by these actions.
            # Or simply yield a timeout of 0 to check again in next delta cycle?
            # Better: The generator that calls this should be triggered by the events.
            pass

    # Actually, a cleaner way in SimPy for this pattern:
    # The Coordinator is a process that waits for a "state change" event.
    # State change events are triggered by:
    # 1. Facility generating a pallet.
    # 2. Aircraft entering 'idle' state.
    
    state_change_event = simpy.Event(env)
    
    # Redefine Coordinator to wait on state_change_event
    def coordinator_process():
        while True:
            # Check assignments
            if loading_queue.has_pallets():
                for ac in aircrafts:
                    if ac.state == "idle" and not coordinator.aircraft_events[ac.id].triggered:
                        pallet = loading_queue.get_next_pallet()
                        if pallet:
                            event_logger.log(env.now, "coordinator", "assignment_created", {
                                "aircraft_id": ac.id,
                                "pallet_id": pallet.id
                            })
                            ac.current_pallet = pallet
                            coordinator.aircraft_events[ac.id].succeed()
                            # Reset the event for the next cycle immediately? 
                            # No, Aircraft run loop resets it when it goes idle again.
                            break
            
            # Wait for next change
            yield state_change_event
            state_change_event = simpy.Event(env) # Reset for next wait

    # Hook up state_change_event triggers
    original_add_pallet = loading_queue.add_pallet
    def wrapped_add_pallet(pallet):
        original_add_pallet(pallet)
        if not state_change_event.triggered:
            state_change_event.succeed()
    
    loading_queue.add_pallet = wrapped_add_pallet

    original_notify_idle = coordinator.notify_idle
    def wrapped_notify_idle(aircraft):
        original_notify_idle(aircraft)
        if not state_change_event.triggered:
            state_change_event.succeed()
            
    coordinator.notify_idle = wrapped_notify_idle
    
    env.process(coordinator_process())

    # Facility Generator
    pallet_id_counter = 0
    
    def facility_generator():
        nonlocal pallet_id_counter
        while True:
            # Generate pallet
            pallet_id_counter += 1
            pid = pallet_id_counter
            gen_time = env.now
            exp_time = gen_time + args.pallet_expiration_time
            
            event_logger.log(gen_time, "facility", "pallet_generated", {
                "pallet_id": pid,
                "expiration_time": round(exp_time, 6)
            })
            
            pallet = Pallet(pid, gen_time, exp_time)
            loading_queue.add_pallet(pallet)
            
            # Wait for next interval
            yield env.timeout(args.pallet_interval)

    env.process(facility_generator())
    
    # Run simulation
    start_real_time = time.time()
    env.run(until=args.duration)
    end_real_time = time.time()
    
    logger.info(f"Simulation completed in {end_real_time - start_real_time:.4f} real seconds.")

def main():
    parser = argparse.ArgumentParser(description="Airfreight Logistics Simulation")
    
    parser.add_argument("--duration", type=float, default=10000.0, help="Total simulation time")
    parser.add_argument("--num_aircraft", type=int, default=2, help="Number of aircraft")
    parser.add_argument("--pallet_interval", type=float, default=25.0, help="Time between pallet generations")
    parser.add_argument("--pallet_expiration_time", type=float, default=150.0, help="Pallet expiration window")
    parser.add_argument("--flight_time", type=float, default=30.0, help="Flight duration")
    parser.add_argument("--unload_time", type=float, default=2.0, help="Unloading duration")
    parser.add_argument("--return_time", type=float, default=30.0, help="Return flight duration")
    parser.add_argument("--maintenance_time", type=float, default=10.0, help="Maintenance duration")
    
    args = parser.parse_args()
    
    try:
        run_simulation(args)
    except Exception as e:
        logger.error(f"Simulation failed: {e}")
        raise

if __name__ == "__main__":
    main()