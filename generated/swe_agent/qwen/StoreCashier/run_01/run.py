#!/usr/bin/env python3
"""
Two-Employee Store Cashier Simulation using SimPy
"""

import argparse
import json
import random
import simpy
from datetime import datetime, timedelta

# Global variables for simulation state
events = []

def format_time(time_value: float) -> str:
    """Convert simulation time to HH:MM:SS:mmm format"""
    hours = int(time_value // 3600)
    minutes = int((time_value % 3600) // 60)
    seconds = int(time_value % 60)
    milliseconds = int((time_value % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"

class Client:
    def __init__(self, client_id: int, arrival_time: float):
        self.client_id = client_id
        self.arrival_time = arrival_time
        self.paired_time = None
        self.employee_id = None

class Employee:
    def __init__(self, env, employee_id: int, mean_service_time: float, std_dev: float):
        self.env = env
        self.employee_id = employee_id
        self.mean_service_time = mean_service_time
        self.std_dev = std_dev
        self.is_available = True
        self.current_client = None
        self.service_start_time = None

    def get_service_duration(self) -> float:
        """Get service duration for this employee based on their mean and std dev"""
        if self.std_dev == 0:
            return self.mean_service_time
        
        # Sample from normal distribution with bounds
        min_duration = self.mean_service_time - 3 * self.std_dev
        max_duration = self.mean_service_time + 3 * self.std_dev
        
        # Generate normally distributed value
        duration = random.normalvariate(self.mean_service_time, self.std_dev)
        
        # Clamp to bounds
        duration = max(min_duration, min(max_duration, duration))
        
        return duration

    def serve_client(self, client: Client):
        """Serve a client"""
        # Record the pairing
        client.paired_time = self.env.now
        client.employee_id = self.employee_id
        
        # Update employee state
        self.is_available = False
        self.current_client = client.client_id
        self.service_start_time = self.env.now
        
        # Emit client_paired event
        event = {
            "time": self.env.now,
            "time_str": format_time(self.env.now),
            "event": "client_paired",
            "entity_type": "queue",
            "entity": "Queue",
            "payload": {
                "client_id": client.client_id,
                "employee_id": self.employee_id,
                "paired_time": self.env.now
            }
        }
        events.append(event)
        
        # Calculate service duration
        service_duration = self.get_service_duration()
        
        # Wait for service to complete
        yield self.env.timeout(service_duration)
        
        # Complete service
        delay = self.env.now - client.arrival_time
        
        # Emit client_served event
        event = {
            "time": self.env.now,
            "time_str": format_time(self.env.now),
            "event": "client_served",
            "entity_type": "employee",
            "entity": f"Employee_{self.employee_id}",
            "payload": {
                "client_id": client.client_id,
                "employee_id": self.employee_id,
                "arrived": client.arrival_time,
                "dispatched": self.env.now,
                "delay": delay
            }
        }
        events.append(event)
        
        # Mark employee as available
        self.is_available = True
        self.current_client = None
        self.service_start_time = None
        
        # Emit employee_available event
        event = {
            "time": self.env.now,
            "time_str": format_time(self.env.now),
            "event": "employee_available",
            "entity_type": "employee",
            "entity": f"Employee_{self.employee_id}",
            "payload": {
                "employee_id": self.employee_id
            }
        }
        events.append(event)

def client_generator(env, client_id_counter, client_mean, client_stddev, employees, queue):
    """Generate clients at specified intervals"""
    while True:
        # Generate interarrival time
        min_interval = 0.0
        max_interval = client_mean + 5 * client_stddev
        
        # Generate normally distributed value
        interval = random.normalvariate(client_mean, client_stddev)
        
        # Clamp to bounds
        interval = max(min_interval, min(max_interval, interval))
        
        # Wait for next arrival
        yield env.timeout(interval)
        
        # Create new client
        client = Client(client_id_counter, env.now)
        
        # Emit client_generated event
        event = {
            "time": env.now,
            "time_str": format_time(env.now),
            "event": "client_generated",
            "entity_type": "client_generator",
            "entity": "ClientGenerator",
            "payload": {
                "client_id": client_id_counter,
                "arrival_time": env.now
            }
        }
        events.append(event)
        
        # Add client to queue
        queue.append(client)
        
        # Try to assign to an available employee
        available_employees = [emp for emp in employees if emp.is_available]
        if available_employees:
            # Assign to first available employee
            employee = available_employees[0]
            # Remove from queue
            queue.remove(client)
            # Serve the client
            env.process(employee.serve_client(client))
        
        client_id_counter += 1

def assign_clients_to_employees(env, employees, queue):
    """Periodically check for available employees and assign waiting clients"""
    while True:
        # Check for available employees
        available_employees = [emp for emp in employees if emp.is_available]
        
        # If there are available employees and waiting clients, assign them
        if available_employees and queue:
            # Take the first client from the queue (FIFO)
            client = queue.pop(0)
            
            # Assign to first available employee
            employee = available_employees[0]
            
            # Serve the client
            env.process(employee.serve_client(client))
        
        # Wait a bit before checking again
        yield env.timeout(0.1)

def main():
    parser = argparse.ArgumentParser(description="Two-Employee Store Cashier Simulation")
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000",
                       help="Total simulation horizon in HH:MM:SS:mmm format")
    parser.add_argument("--client_mean", type=float, default=10.0)
    parser.add_argument("--client_stddev", type=float, default=5.0)
    parser.add_argument("--employee_1_mean", type=float, default=20.0)
    parser.add_argument("--employee_1_stddev", type=float, default=0.0)
    parser.add_argument("--employee_2_mean", type=float, default=30.0)
    parser.add_argument("--employee_2_stddev", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=None)
    
    args = parser.parse_args()
    
    # Parse simulation time
    time_parts = args.simulation_time.split(":")
    hours = int(time_parts[0])
    minutes = int(time_parts[1])
    seconds = int(time_parts[2])
    milliseconds = int(time_parts[3])
    
    simulation_horizon = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    
    # Set seed if provided
    if args.seed is not None:
        random.seed(args.seed)
    
    # Create environment
    env = simpy.Environment()
    
    # Initialize employees
    employees = [
        Employee(env, 1, args.employee_1_mean, args.employee_1_stddev),
        Employee(env, 2, args.employee_2_mean, args.employee_2_stddev)
    ]
    
    # Initialize queue
    queue = []
    
    # Emit initial employee available events
    for employee in employees:
        event = {
            "time": 0.0,
            "time_str": "00:00:00:000",
            "event": "employee_available",
            "entity_type": "employee",
            "entity": f"Employee_{employee.employee_id}",
            "payload": {
                "employee_id": employee.employee_id
            }
        }
        events.append(event)
    
    # Start client generator
    env.process(client_generator(env, 1, args.client_mean, args.client_stddev, employees, queue))
    
    # Start the assignment process
    env.process(assign_clients_to_employees(env, employees, queue))
    
    # Run simulation
    env.run(until=simulation_horizon)
    
    # Sort events by time
    events.sort(key=lambda x: x["time"])
    
    # Print events
    for event in events:
        print(json.dumps(event))

if __name__ == "__main__":
    main()