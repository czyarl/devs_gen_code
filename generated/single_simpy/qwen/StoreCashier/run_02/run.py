import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from typing import List, Tuple, Optional

# Event types
EMPLOYEE_AVAILABLE = "employee_available"
CLIENT_GENERATED = "client_generated"
CLIENT_PAIRED = "client_paired"
CLIENT_SERVED = "client_served"

# Entity types
EMPLOYEE = "employee"
CLIENT_GENERATOR = "client_generator"
QUEUE = "queue"

# Entities
EMPLOYEE_1 = "Employee_1"
EMPLOYEE_2 = "Employee_2"
CLIENT_GENERATOR_ENTITY = "ClientGenerator"
QUEUE_ENTITY = "Queue"

# Default parameters
DEFAULT_CLIENT_MEAN = 10.0
DEFAULT_CLIENT_STDDEV = 5.0
DEFAULT_EMPLOYEE_1_MEAN = 20.0
DEFAULT_EMPLOYEE_1_STDDEV = 0.0
DEFAULT_EMPLOYEE_2_MEAN = 30.0
DEFAULT_EMPLOYEE_2_STDDEV = 4.0
DEFAULT_SIMULATION_TIME = "00:05:00:000"

def format_time(seconds: float) -> str:
    """Convert seconds to HH:MM:SS:mmm format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millisecs = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{millisecs:03d}"

def parse_time(time_str: str) -> float:
    """Parse HH:MM:SS:mmm format to seconds."""
    h, m, s, ms = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s + ms / 1000.0

def clamp(value: float, min_val: float, max_val: float) -> float:
    """Clamp a value between min and max."""
    return max(min_val, min(max_val, value))

def generate_interarrival_time(mean: float, stddev: float) -> float:
    """Generate interarrival time with normal distribution constraints."""
    if stddev == 0:
        return mean
    # Generate normally distributed value
    value = random.gauss(mean, stddev)
    # Clamp to allowed range
    min_val = 0
    max_val = mean + 5 * stddev
    return clamp(value, min_val, max_val)

def generate_service_time(mean: float, stddev: float) -> float:
    """Generate service time with normal distribution constraints."""
    if stddev == 0:
        return mean
    # Generate normally distributed value
    value = random.gauss(mean, stddev)
    # Clamp to allowed range
    min_val = mean - 3 * stddev
    max_val = mean + 3 * stddev
    return clamp(value, min_val, max_val)

class Client:
    def __init__(self, client_id: int, arrival_time: float):
        self.client_id = client_id
        self.arrival_time = arrival_time

class Event:
    def __init__(self, time: float, event_type: str, entity_type: str, entity: str, payload: dict):
        self.time = time
        self.event_type = event_type
        self.entity_type = entity_type
        self.entity = entity
        self.payload = payload

    def to_json(self) -> str:
        """Convert event to JSONL format."""
        obj = {
            "time": self.time,
            "time_str": format_time(self.time),
            "event": self.event_type,
            "entity_type": self.entity_type,
            "entity": self.entity,
            "payload": self.payload
        }
        return json.dumps(obj)

class Employee:
    def __init__(self, employee_id: int, mean: float, stddev: float):
        self.employee_id = employee_id
        self.mean = mean
        self.stddev = stddev
        self.is_available = True
        self.current_client = None
        self.service_start_time = None

    def start_service(self, client: Client, start_time: float):
        """Start serving a client."""
        self.current_client = client
        self.service_start_time = start_time
        self.is_available = False

    def complete_service(self, completion_time: float) -> Client:
        """Complete service and return the client."""
        client = self.current_client
        self.current_client = None
        self.service_start_time = None
        self.is_available = True
        return client

class StoreSimulation:
    def __init__(self, 
                 client_mean: float, 
                 client_stddev: float,
                 employee_1_mean: float,
                 employee_1_stddev: float,
                 employee_2_mean: float,
                 employee_2_stddev: float,
                 simulation_time: float):
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.employee_1_mean = employee_1_mean
        self.employee_1_stddev = employee_1_stddev
        self.employee_2_mean = employee_2_mean
        self.employee_2_stddev = employee_2_stddev
        self.simulation_time = simulation_time
        
        self.clients = []  # List of all generated clients
        self.client_id_counter = 1
        self.queue = []  # FIFO queue of waiting clients
        self.employees = [
            Employee(1, employee_1_mean, employee_1_stddev),
            Employee(2, employee_2_mean, employee_2_stddev)
        ]
        
        self.events: List[Event] = []
        self.next_client_arrival_time = 0.0

    def generate_client(self, arrival_time: float):
        """Generate a new client."""
        client = Client(self.client_id_counter, arrival_time)
        self.clients.append(client)
        self.client_id_counter += 1
        
        # Add client generated event
        event = Event(
            time=arrival_time,
            event_type=CLIENT_GENERATED,
            entity_type=CLIENT_GENERATOR,
            entity=CLIENT_GENERATOR_ENTITY,
            payload={
                "client_id": client.client_id,
                "arrival_time": arrival_time
            }
        )
        self.events.append(event)
        
        # Add to queue
        self.queue.append(client)
        self.pair_client_if_possible(arrival_time)

    def pair_client_if_possible(self, time: float):
        """Pair a waiting client with an available employee."""
        # Find an available employee
        available_employee = None
        for emp in self.employees:
            if emp.is_available:
                available_employee = emp
                break
        
        if available_employee and self.queue:
            # Get the first client in queue
            client = self.queue[0]
            
            # Remove client from queue
            self.queue.pop(0)
            
            # Start service
            service_time = generate_service_time(available_employee.mean, available_employee.stddev)
            available_employee.start_service(client, time)
            
            # Add client paired event
            event = Event(
                time=time,
                event_type=CLIENT_PAIRED,
                entity_type=QUEUE,
                entity=QUEUE_ENTITY,
                payload={
                    "client_id": client.client_id,
                    "employee_id": available_employee.employee_id,
                    "paired_time": time
                }
            )
            self.events.append(event)
            
            # Schedule service completion
            completion_time = time + service_time
            self.schedule_service_completion(available_employee, completion_time)

    def schedule_service_completion(self, employee: Employee, completion_time: float):
        """Schedule completion of service for an employee."""
        # Add employee available event
        event = Event(
            time=completion_time,
            event_type=EMPLOYEE_AVAILABLE,
            entity_type=EMPLOYEE,
            entity=EMPLOYEE_1 if employee.employee_id == 1 else EMPLOYEE_2,
            payload={
                "employee_id": employee.employee_id
            }
        )
        self.events.append(event)
        
        # Add client served event
        client = employee.complete_service(completion_time)
        delay = completion_time - client.arrival_time
        
        event = Event(
            time=completion_time,
            event_type=CLIENT_SERVED,
            entity_type=EMPLOYEE,
            entity=EMPLOYEE_1 if employee.employee_id == 1 else EMPLOYEE_2,
            payload={
                "client_id": client.client_id,
                "employee_id": employee.employee_id,
                "arrived": client.arrival_time,
                "dispatched": completion_time,
                "delay": delay
            }
        )
        self.events.append(event)
        
        # Try to pair next client
        self.pair_client_if_possible(completion_time)

    def run(self):
        """Run the simulation."""
        # Initial employee availability
        for emp in self.employees:
            event = Event(
                time=0.0,
                event_type=EMPLOYEE_AVAILABLE,
                entity_type=EMPLOYEE,
                entity=EMPLOYEE_1 if emp.employee_id == 1 else EMPLOYEE_2,
                payload={
                    "employee_id": emp.employee_id
                }
            )
            self.events.append(event)
        
        # Generate first client
        self.generate_client(0.0)
        
        # Continue generating clients until simulation time
        while self.next_client_arrival_time < self.simulation_time:
            # Generate interarrival time
            interarrival = generate_interarrival_time(self.client_mean, self.client_stddev)
            self.next_client_arrival_time += interarrival
            
            if self.next_client_arrival_time <= self.simulation_time:
                self.generate_client(self.next_client_arrival_time)
        
        # Sort events by time
        self.events.sort(key=lambda e: e.time)

def main():
    parser = argparse.ArgumentParser(description="Two-Employee Store Cashier Simulation")
    parser.add_argument("--simulation_time", type=str, default=DEFAULT_SIMULATION_TIME,
                        help="Total simulation horizon in HH:MM:SS:mmm format. Default: 00:05:00:000")
    parser.add_argument("--client_mean", type=float, default=DEFAULT_CLIENT_MEAN,
                        help="Client inter-arrival mean. Default: 10.0")
    parser.add_argument("--client_stddev", type=float, default=DEFAULT_CLIENT_STDDEV,
                        help="Client inter-arrival standard deviation. Default: 5.0")
    parser.add_argument("--employee_1_mean", type=float, default=DEFAULT_EMPLOYEE_1_MEAN,
                        help="Employee 1 service mean. Default: 20.0")
    parser.add_argument("--employee_1_stddev", type=float, default=DEFAULT_EMPLOYEE_1_STDDEV,
                        help="Employee 1 service standard deviation. Default: 0.0")
    parser.add_argument("--employee_2_mean", type=float, default=DEFAULT_EMPLOYEE_2_MEAN,
                        help="Employee 2 service mean. Default: 30.0")
    parser.add_argument("--employee_2_stddev", type=float, default=DEFAULT_EMPLOYEE_2_STDDEV,
                        help="Employee 2 service standard deviation. Default: 4.0")
    
    args = parser.parse_args()
    
    # Parse simulation time
    simulation_time = parse_time(args.simulation_time)
    
    # Initialize random seed for reproducibility
    random.seed(42)
    
    # Create and run simulation
    sim = StoreSimulation(
        client_mean=args.client_mean,
        client_stddev=args.client_stddev,
        employee_1_mean=args.employee_1_mean,
        employee_1_stddev=args.employee_1_stddev,
        employee_2_mean=args.employee_2_mean,
        employee_2_stddev=args.employee_2_stddev,
        simulation_time=simulation_time
    )
    
    sim.run()
    
    # Output events in JSONL format
    for event in sim.events:
        print(event.to_json())

if __name__ == "__main__":
    main()