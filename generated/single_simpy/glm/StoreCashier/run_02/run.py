import argparse
import json
import random
import sys
import simpy
from dataclasses import dataclass, field
from typing import Optional

# --- Constants and Configuration ---

DEFAULT_SIMULATION_TIME = "00:05:00:000"
DEFAULT_CLIENT_MEAN = 10.0
DEFAULT_CLIENT_STDDEV = 5.0
DEFAULT_EMPLOYEE_1_MEAN = 20.0
DEFAULT_EMPLOYEE_1_STDDEV = 0.0
DEFAULT_EMPLOYEE_2_MEAN = 30.0
DEFAULT_EMPLOYEE_2_STDDEV = 4.0


# --- Helper Functions ---

def parse_time_str(time_str: str) -> float:
    """
    Parses a time string in HH:MM:SS:mmm format to total seconds.
    """
    parts = time_str.split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {time_str}. Expected HH:MM:SS:mmm")
    
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0

def format_time_str(total_seconds: float) -> str:
    """
    Formats total seconds to HH:MM:SS:mmm string.
    """
    hours = int(total_seconds // 3600)
    remainder = total_seconds % 3600
    minutes = int(remainder // 60)
    remainder = remainder % 60
    seconds = int(remainder // 1)
    milliseconds = int(round((remainder - seconds) * 1000))
    
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"

def get_truncated_normal(mean: float, stddev: float, min_val: float, max_val: float) -> float:
    """
    Samples from a normal distribution and truncates the result to [min_val, max_val].
    If stddev is 0, returns mean.
    """
    if stddev == 0:
        return mean
    
    value = random.gauss(mean, stddev)
    return max(min_val, min(max_val, value))

def log_event(env: simpy.Environment, event_type: str, entity_type: str, entity: str, payload: dict):
    """
    Prints a JSONL event to stdout.
    """
    data = {
        "time": env.now,
        "time_str": format_time_str(env.now),
        "event": event_type,
        "entity_type": entity_type,
        "entity": entity,
        "payload": payload
    }
    print(json.dumps(data))


# --- Simulation Components ---

@dataclass
class Client:
    id: int
    arrival_time: float

def client_generator(env: simpy.Environment, queue: simpy.Store, params: dict):
    """
    Generates clients over time.
    """
    client_id = 1
    horizon = params['simulation_time']
    
    # The first client is generated at t = 0.0
    while env.now < horizon:
        # 1. Generate Client
        log_event(
            env, 
            "client_generated", 
            "client_generator", 
            "ClientGenerator", 
            {"client_id": client_id, "arrival_time": env.now}
        )
        
        client = Client(id=client_id, arrival_time=env.now)
        yield queue.put(client)
        
        client_id += 1
        
        # 2. Schedule next generation
        # Inter-arrival: 0 <= interval <= mean + 5 * stddev
        interval = get_truncated_normal(
            params['client_mean'],
            params['client_stddev'],
            0.0,
            params['client_mean'] + 5 * params['client_stddev']
        )
        
        # If the next generation time is past the horizon, stop.
        if env.now + interval > horizon:
            break
            
        yield env.timeout(interval)

def employee_process(env: simpy.Environment, queue: simpy.Store, employee_id: int, params: dict):
    """
    Represents an employee serving clients.
    """
    emp_name = f"Employee_{employee_id}"
    mean = params[f'employee_{employee_id}_mean']
    stddev = params[f'employee_{employee_id}_stddev']
    
    # Initial availability at t = 0.0
    log_event(
        env,
        "employee_available",
        "employee",
        emp_name,
        {"employee_id": employee_id}
    )
    
    while True:
        # Wait for a client from the queue
        # This blocks if the queue is empty
        client = yield queue.get()
        
        # Pairing is instantaneous
        paired_time = env.now
        log_event(
            env,
            "client_paired",
            "queue",
            "Queue",
            {"client_id": client.id, "employee_id": employee_id, "paired_time": paired_time}
        )
        
        # Determine service duration
        # Range: mean - 3*stddev <= duration <= mean + 3*stddev
        duration = get_truncated_normal(
            mean,
            stddev,
            mean - 3 * stddev,
            mean + 3 * stddev
        )
        
        # Ensure duration is not negative (safety check for weird params)
        if duration < 0:
            duration = 0.0
            
        yield env.timeout(duration)
        
        # Service completed
        dispatched = env.now
        delay = dispatched - client.arrival_time
        
        log_event(
            env,
            "client_served",
            "employee",
            emp_name,
            {
                "client_id": client.id,
                "employee_id": employee_id,
                "arrived": client.arrival_time,
                "dispatched": dispatched,
                "delay": delay
            }
        )
        
        # Employee becomes available again
        log_event(
            env,
            "employee_available",
            "employee",
            emp_name,
            {"employee_id": employee_id}
        )

def main():
    parser = argparse.ArgumentParser(description="Two-Employee Store Cashier Simulation")
    parser.add_argument(
        "--simulation_time", 
        type=str, 
        default=DEFAULT_SIMULATION_TIME,
        help="Total simulation horizon in HH:MM:SS:mmm format"
    )
    parser.add_argument("--client_mean", type=float, default=DEFAULT_CLIENT_MEAN)
    parser.add_argument("--client_stddev", type=float, default=DEFAULT_CLIENT_STDDEV)
    parser.add_argument("--employee_1_mean", type=float, default=DEFAULT_EMPLOYEE_1_MEAN)
    parser.add_argument("--employee_1_stddev", type=float, default=DEFAULT_EMPLOYEE_1_STDDEV)
    parser.add_argument("--employee_2_mean", type=float, default=DEFAULT_EMPLOYEE_2_MEAN)
    parser.add_argument("--employee_2_stddev", type=float, default=DEFAULT_EMPLOYEE_2_STDDEV)
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")

    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    # Convert simulation time string to seconds
    try:
        horizon_seconds = parse_time_str(args.simulation_time)
    except ValueError as e:
        print(f"Error parsing simulation time: {e}", file=sys.stderr)
        sys.exit(1)

    # Setup parameters dictionary
    params = {
        'simulation_time': horizon_seconds,
        'client_mean': args.client_mean,
        'client_stddev': args.client_stddev,
        'employee_1_mean': args.employee_1_mean,
        'employee_1_stddev': args.employee_1_stddev,
        'employee_2_mean': args.employee_2_mean,
        'employee_2_stddev': args.employee_2_stddev,
    }

    # Setup SimPy Environment
    env = simpy.Environment()
    queue = simpy.Store(env) # FIFO Queue

    # Start processes
    # We start the generator first so client_generated happens before employee_available 
    # if they occur at the exact same timestamp t=0, though order isn't strictly enforced by SimPy
    # at the same time step unless priorities are used. However, logically, 
    # the generator runs, puts client, then employees run and pick it up.
    env.process(client_generator(env, queue, params))
    env.process(employee_process(env, queue, 1, params))
    env.process(employee_process(env, queue, 2, params))

    # Run simulation
    # Events scheduled after the horizon will not be processed by SimPy
    env.run(until=horizon_seconds)

if __name__ == "__main__":
    main()