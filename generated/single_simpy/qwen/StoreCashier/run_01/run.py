import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from typing import List, Tuple

# Global variables for simulation state
clients = []
employees = [None, None]  # Employee 1 and 2
queue = []
next_client_id = 1
simulation_time = 0.0
simulation_horizon = 0.0
client_mean = 10.0
client_stddev = 5.0
employee_1_mean = 20.0
employee_1_stddev = 0.0
employee_2_mean = 30.0
employee_2_stddev = 4.0
random.seed(42)  # For reproducibility


def format_time(seconds: float) -> str:
    """Convert seconds to HH:MM:SS:mmm format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millisecs = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{millisecs:03d}"


def generate_client():
    """Generate a new client at current simulation time"""
    global next_client_id, simulation_time
    
    arrival_time = simulation_time
    client_id = next_client_id
    next_client_id += 1
    
    # Create client record
    client = {
        'id': client_id,
        'arrival_time': arrival_time,
        'paired_time': None,
        'served_time': None,
        'delay': None
    }
    
    clients.append(client)
    
    # Emit client_generated event
    event = {
        'time': simulation_time,
        'time_str': format_time(simulation_time),
        'event': 'client_generated',
        'entity_type': 'client_generator',
        'entity': 'ClientGenerator',
        'payload': {
            'client_id': client_id,
            'arrival_time': arrival_time
        }
    }
    
    print(json.dumps(event))
    return client


def get_service_duration(employee_id: int) -> float:
    """Get service duration for an employee based on their parameters"""
    if employee_id == 1:
        mean = employee_1_mean
        stddev = employee_1_stddev
    else:
        mean = employee_2_mean
        stddev = employee_2_stddev
    
    if stddev == 0:
        return mean
    
    # Generate normally distributed value within bounds
    while True:
        duration = random.normalvariate(mean, stddev)
        min_duration = mean - 3 * stddev
        max_duration = mean + 3 * stddev
        
        if min_duration <= duration <= max_duration:
            return duration


def pair_client_with_employee(client_id: int, employee_id: int):
    """Pair a client with an employee"""
    global employees, queue
    
    # Find the client
    client = None
    for c in clients:
        if c['id'] == client_id:
            client = c
            break
    
    if client is None:
        raise ValueError(f"Client {client_id} not found")
    
    # Mark client as paired
    client['paired_time'] = simulation_time
    
    # Assign employee
    employees[employee_id - 1] = client_id
    
    # Emit client_paired event
    event = {
        'time': simulation_time,
        'time_str': format_time(simulation_time),
        'event': 'client_paired',
        'entity_type': 'queue',
        'entity': 'Queue',
        'payload': {
            'client_id': client_id,
            'employee_id': employee_id,
            'paired_time': simulation_time
        }
    }
    
    print(json.dumps(event))


def serve_client(client_id: int, employee_id: int):
    """Serve a client with an employee"""
    global employees, queue
    
    # Find the client
    client = None
    for c in clients:
        if c['id'] == client_id:
            client = c
            break
    
    if client is None:
        raise ValueError(f"Client {client_id} not found")
    
    # Calculate delay
    delay = simulation_time - client['arrival_time']
    client['delay'] = delay
    
    # Mark client as served
    client['served_time'] = simulation_time
    
    # Release employee
    employees[employee_id - 1] = None
    
    # Emit client_served event
    event = {
        'time': simulation_time,
        'time_str': format_time(simulation_time),
        'event': 'client_served',
        'entity_type': 'employee',
        'entity': f'Employee_{employee_id}',
        'payload': {
            'client_id': client_id,
            'employee_id': employee_id,
            'arrived': client['arrival_time'],
            'dispatched': simulation_time,
            'delay': delay
        }
    }
    
    print(json.dumps(event))
    
    # Emit employee_available event
    event = {
        'time': simulation_time,
        'time_str': format_time(simulation_time),
        'event': 'employee_available',
        'entity_type': 'employee',
        'entity': f'Employee_{employee_id}',
        'payload': {
            'employee_id': employee_id
        }
    }
    
    print(json.dumps(event))


def process_queue():
    """Process the queue of waiting clients"""
    global queue, employees
    
    # Try to pair waiting clients with available employees
    for i in range(len(employees)):
        if employees[i] is None and queue:
            # An employee is available and there are clients waiting
            client = queue.pop(0)
            pair_client_with_employee(client['id'], i + 1)


def main():
    global simulation_time, simulation_horizon, client_mean, client_stddev, \
           employee_1_mean, employee_1_stddev, employee_2_mean, employee_2_stddev
    
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulation_time', type=str, default="00:05:00:000")
    parser.add_argument('--client_mean', type=float, default=10.0)
    parser.add_argument('--client_stddev', type=float, default=5.0)
    parser.add_argument('--employee_1_mean', type=float, default=20.0)
    parser.add_argument('--employee_1_stddev', type=float, default=0.0)
    parser.add_argument('--employee_2_mean', type=float, default=30.0)
    parser.add_argument('--employee_2_stddev', type=float, default=4.0)
    parser.add_argument('--seed', type=int, default=None)
    
    args = parser.parse_args()
    
    # Parse simulation time
    time_parts = args.simulation_time.split(':')
    hours, minutes, seconds, milliseconds = map(int, time_parts)
    simulation_horizon = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    
    # Set parameters
    client_mean = args.client_mean
    client_stddev = args.client_stddev
    employee_1_mean = args.employee_1_mean
    employee_1_stddev = args.employee_1_stddev
    employee_2_mean = args.employee_2_mean
    employee_2_stddev = args.employee_2_stddev
    
    if args.seed is not None:
        random.seed(args.seed)
    
    # Initialize simulation
    simulation_time = 0.0
    
    # Initial employee availability
    for i in range(1, 3):
        event = {
            'time': simulation_time,
            'time_str': format_time(simulation_time),
            'event': 'employee_available',
            'entity_type': 'employee',
            'entity': f'Employee_{i}',
            'payload': {
                'employee_id': i
            }
        }
        print(json.dumps(event))
    
    # Generate first client
    generate_client()
    
    # Main simulation loop
    while simulation_time < simulation_horizon:
        # Determine next event time
        next_arrival_time = simulation_time + random.normalvariate(client_mean, client_stddev)
        
        # Ensure arrival time is within bounds
        min_arrival = simulation_time
        max_arrival = simulation_time + client_mean + 5 * client_stddev
        
        if next_arrival_time < min_arrival:
            next_arrival_time = min_arrival
        elif next_arrival_time > max_arrival:
            next_arrival_time = max_arrival
            
        # If we're beyond the horizon, stop
        if next_arrival_time >= simulation_horizon:
            break
            
        # Advance time to next arrival
        simulation_time = next_arrival_time
        
        # Generate new client
        generate_client()
        
        # Process queue
        process_queue()
        
        # Serve any clients that can be served now
        for i in range(len(employees)):
            if employees[i] is not None:
                # Get the client being served
                client_id = employees[i]
                client = None
                for c in clients:
                    if c['id'] == client_id:
                        client = c
                        break
                
                if client and client['paired_time'] is not None:
                    # Calculate when service will end
                    service_duration = get_service_duration(i + 1)
                    service_end_time = client['paired_time'] + service_duration
                    
                    # If service is done, serve the client
                    if service_end_time <= simulation_time:
                        serve_client(client_id, i + 1)
                        
                        # Process queue again after serving
                        process_queue()
    
    # Handle remaining clients in queue
    while queue:
        process_queue()
        # Check if any employee can serve a client
        for i in range(len(employees)):
            if employees[i] is not None:
                # Get the client being served
                client_id = employees[i]
                client = None
                for c in clients:
                    if c['id'] == client_id:
                        client = c
                        break
                
                if client and client['paired_time'] is not None:
                    # Calculate when service will end
                    service_duration = get_service_duration(i + 1)
                    service_end_time = client['paired_time'] + service_duration
                    
                    # If service is done, serve the client
                    if service_end_time <= simulation_time:
                        serve_client(client_id, i + 1)
                        # Process queue again after serving
                        process_queue()
                        break
        else:
            # No employees are currently serving, so advance time to next possible event
            break

if __name__ == "__main__":
    main()