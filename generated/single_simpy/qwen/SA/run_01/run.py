import argparse
import sys
import json
import logging
import random
from collections import deque
from typing import Dict, Any, List
import time

# Simulation time tracking
sim_time = 0.0

# Event queue for simulation
event_queue = []

# Global state
pallet_id_counter = 0
aircraft_id_counter = 0
expired_count = 0
aircraft_states = {}  # aircraft_id -> state
aircraft_pallets = {}  # aircraft_id -> pallet_id
aircraft_timers = {}  # aircraft_id -> {state: time}
aircraft_next_state = {}  # aircraft_id -> next_state
aircraft_return_times = {}  # aircraft_id -> return_time
aircraft_maintenance_times = {}  # aircraft_id -> maintenance_time
aircraft_flight_times = {}  # aircraft_id -> flight_time
aircraft_unload_times = {}  # aircraft_id -> unload_time
aircraft_queue = deque()  # queue of (aircraft_id, pallet_id) assignments
pallet_queue = deque()  # queue of pallets waiting for assignment
pallet_expirations = {}  # pallet_id -> expiration_time
pallet_generation_times = {}  # pallet_id -> generation_time
pallet_deliveries = []  # list of (pallet_id, aircraft_id, latency)
aircraft_idle = set()  # set of idle aircraft IDs
aircraft_maintenance = set()  # set of aircraft in maintenance

# Configuration
config = {}

def log_event(time, entity, event, payload):
    """Log an event to stdout as JSONL"""
    event_data = {
        "time": time,
        "entity": entity,
        "event": event,
        "payload": payload
    }
    print(json.dumps(event_data))

def log_debug(message):
    """Log debug information to stderr"""
    print(message, file=sys.stderr)

def generate_pallet():
    """Generate a new pallet and add to queue"""
    global pallet_id_counter, sim_time
    pallet_id = pallet_id_counter
    pallet_id_counter += 1
    expiration_time = sim_time + config['pallet_expiration_time']
    
    pallet_expirations[pallet_id] = expiration_time
    pallet_generation_times[pallet_id] = sim_time
    
    # Add to queue
    pallet_queue.append(pallet_id)
    
    # Log event
    log_event(
        sim_time,
        "facility",
        "pallet_generated",
        {
            "pallet_id": pallet_id,
            "expiration_time": expiration_time
        }
    )
    
    # Log queue event
    log_event(
        sim_time,
        "queue",
        "pallet_queued",
        {
            "pallet_id": pallet_id,
            "queue_size": len(pallet_queue)
        }
    )
    
    return pallet_id

def check_expiration():
    """Check for expired pallets in queue"""
    global expired_count
    to_remove = []
    
    for pallet_id in pallet_queue:
        if sim_time >= pallet_expirations[pallet_id]:
            to_remove.append(pallet_id)
            expired_count += 1
            # Log expiration
            log_event(
                sim_time,
                "queue",
                "pallet_expired",
                {
                    "pallet_id": pallet_id,
                    "total_expired": expired_count
                }
            )
    
    # Remove expired pallets from queue
    for pallet_id in to_remove:
        pallet_queue.remove(pallet_id)

def assign_pallet():
    """Assign pallet to an idle aircraft if available"""
    if not pallet_queue or not aircraft_idle:
        return
    
    # Take the oldest pallet
    pallet_id = pallet_queue.popleft()
    
    # Take the first idle aircraft
    aircraft_id = aircraft_idle.pop()
    
    # Record assignment
    aircraft_pallets[aircraft_id] = pallet_id
    
    # Log assignment
    log_event(
        sim_time,
        "coordinator",
        "assignment_created",
        {
            "aircraft_id": aircraft_id,
            "pallet_id": pallet_id
        }
    )
    
    # Log departure (instantly after assignment)
    log_event(
        sim_time,
        "aircraft",
        "depart",
        {
            "aircraft_id": aircraft_id,
            "pallet_id": pallet_id
        }
    )
    
    # Schedule flight
    flight_end_time = sim_time + config['flight_time']
    aircraft_timers[aircraft_id] = {
        "state": "flying",
        "end_time": flight_end_time
    }

def aircraft_flight_end(aircraft_id):
    """Handle aircraft flight completion"""
    # Schedule unload
    unload_end_time = sim_time + config['unload_time']
    aircraft_timers[aircraft_id] = {
        "state": "unloading",
        "end_time": unload_end_time
    }

def aircraft_unload_end(aircraft_id):
    """Handle aircraft unload completion"""
    pallet_id = aircraft_pallets[aircraft_id]
    aircraft_pallets.pop(aircraft_id, None)
    
    # Calculate latency
    latency = sim_time - pallet_generation_times[pallet_id]
    
    # Log delivery
    log_event(
        sim_time,
        "destination",
        "pallet_delivered",
        {
            "pallet_id": pallet_id,
            "aircraft_id": aircraft_id,
            "latency": latency
        }
    )
    
    # Schedule return
    return_end_time = sim_time + config['return_time']
    aircraft_timers[aircraft_id] = {
        "state": "returning",
        "end_time": return_end_time
    }

def aircraft_return_end(aircraft_id):
    """Handle aircraft return completion"""
    # Schedule maintenance
    maintenance_end_time = sim_time + config['maintenance_time']
    aircraft_timers[aircraft_id] = {
        "state": "maintenance",
        "end_time": maintenance_end_time
    }
    
    # Log return
    log_event(
        sim_time,
        "aircraft",
        "return",
        {
            "aircraft_id": aircraft_id
        }
    )

def aircraft_maintenance_end(aircraft_id):
    """Handle aircraft maintenance completion"""
    # Aircraft back to idle
    aircraft_idle.add(aircraft_id)
    
    # Log maintenance end
    log_event(
        sim_time,
        "aircraft",
        "maintenance_end",
        {
            "aircraft_id": aircraft_id
        }
    )

def process_aircraft_timers():
    """Process all aircraft timers"""
    to_remove = []
    
    for aircraft_id, timer in aircraft_timers.items():
        if sim_time >= timer["end_time"]:
            state = timer["state"]
            to_remove.append(aircraft_id)
            
            if state == "flying":
                aircraft_flight_end(aircraft_id)
            elif state == "unloading":
                aircraft_unload_end(aircraft_id)
            elif state == "returning":
                aircraft_return_end(aircraft_id)
            elif state == "maintenance":
                aircraft_maintenance_end(aircraft_id)
    
    # Remove processed timers
    for aircraft_id in to_remove:
        aircraft_timers.pop(aircraft_id, None)

def main():
    global sim_time, config
    
    # Parse arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--duration', type=float, default=10000.0)
    parser.add_argument('--num_aircraft', type=int, default=2)
    parser.add_argument('--pallet_interval', type=float, default=25.0)
    parser.add_argument('--pallet_expiration_time', type=float, default=150.0)
    parser.add_argument('--flight_time', type=float, default=30.0)
    parser.add_argument('--unload_time', type=float, default=2.0)
    parser.add_argument('--return_time', type=float, default=30.0)
    parser.add_argument('--maintenance_time', type=float, default=10.0)
    
    args = parser.parse_args()
    
    # Set configuration
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
    
    # Initialize aircraft
    for i in range(config['num_aircraft']):
        aircraft_id = i + 1
        aircraft_idle.add(aircraft_id)
        aircraft_states[aircraft_id] = "idle"
        aircraft_pallets[aircraft_id] = None
        aircraft_timers[aircraft_id] = {}
    
    # Simulation loop
    log_debug(f"Starting simulation with config: {config}")
    
    # Generate first pallet
    generate_pallet()
    
    # Main simulation loop
    while sim_time < config['duration']:
        # Process expiration
        check_expiration()
        
        # Assign pallets to idle aircraft
        assign_pallet()
        
        # Process aircraft timers
        process_aircraft_timers()
        
        # Generate new pallets
        if sim_time % config['pallet_interval'] < 1e-6:
            generate_pallet()
        
        # Advance time
        # Find next event time
        next_event_time = config['duration']
        
        # Check for pending aircraft events
        for timer in aircraft_timers.values():
            if timer.get("end_time", float('inf')) < next_event_time:
                next_event_time = timer["end_time"]
        
        # If no events, advance by a small amount
        if next_event_time == config['duration']:
            sim_time += 1.0
        else:
            sim_time = next_event_time
            
        # Ensure we don't exceed duration
        if sim_time > config['duration']:
            sim_time = config['duration']
            
        # Stop if we've run out of time
        if sim_time >= config['duration']:
            break
    
    # Final log of expired pallets
    log_event(
        sim_time,
        "queue",
        "pallet_expired",
        {
            "pallet_id": -1,  # Sentinel value
            "total_expired": expired_count
        }
    )
    
    # Log final aircraft states
    for aircraft_id in range(1, config['num_aircraft'] + 1):
        log_event(
            sim_time,
            "aircraft",
            "maintenance_end",
            {
                "aircraft_id": aircraft_id
            }
        )

if __name__ == "__main__":
    main()