#!/usr/bin/env python3
"""
Store Cashier Simulation - Discrete Event Simulation using SimPy

Simulates a store with two employees serving clients from a FIFO queue.
"""

import argparse
import json
import random
import sys
from typing import List, Dict, Any
import simpy


class EventLogger:
    """Handles logging events in JSONL format."""
    
    def __init__(self):
        self.events: List[Dict[str, Any]] = []
    
    def log_event(self, time: float, event_type: str, entity_type: str, 
                  entity: str, payload: Dict[str, Any]) -> None:
        """Log an event with the specified details."""
        self.events.append({
            "time": time,
            "time_str": format_time(time),
            "event": event_type,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload
        })
    
    def print_events(self) -> None:
        """Print all events in JSONL format."""
        for event in self.events:
            print(json.dumps(event))


def format_time(seconds: float) -> str:
    """Convert seconds to HH:MM:SS:mmm format."""
    total_ms = int(seconds * 1000)
    hours = total_ms // 3600000
    minutes = (total_ms % 3600000) // 60000
    secs = (total_ms % 60000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{millis:03d}"


def parse_time(time_str: str) -> float:
    """Parse HH:MM:SS:mmm format to seconds."""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    millis = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def bounded_normal(mean: float, stddev: float, lower_mult: float = 0, 
                   upper_mult: float = 5) -> float:
    """Sample from bounded normal distribution."""
    if stddev == 0:
        return mean
    
    lower_bound = mean - lower_mult * stddev
    upper_bound = mean + upper_mult * stddev
    
    while True:
        value = random.gauss(mean, stddev)
        if lower_bound <= value <= upper_bound:
            return value


class StoreSimulation:
    """Main simulation class for the store cashier system."""
    
    def __init__(self, simulation_time: float, client_mean: float, 
                 client_stddev: float, employee_1_mean: float,
                 employee_1_stddev: float, employee_2_mean: float,
                 employee_2_stddev: float, seed: int = None):
        self.simulation_time = simulation_time
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.employee_1_mean = employee_1_mean
        self.employee_1_stddev = employee_1_stddev
        self.employee_2_mean = employee_2_mean
        self.employee_2_stddev = employee_2_stddev
        
        if seed is not None:
            random.seed(seed)
        
        self.logger = EventLogger()
        self.client_counter = 0
        self.queue: List[Dict[str, Any]] = []
        self.employee_status = {1: True, 2: True}  # True = available
        self.paired_clients: Dict[int, float] = {}  # client_id -> paired_time
    
    def run(self):
        """Run the simulation."""
        env = simpy.Environment()
        
        # Log initial employee availability
        self.logger.log_event(0.0, "employee_available", "employee", 
                             "Employee_1", {"employee_id": 1})
        self.logger.log_event(0.0, "employee_available", "employee", 
                             "Employee_2", {"employee_id": 2})
        
        # Start client generator
        env.process(self.client_generator(env))
        
        # Run simulation
        env.run(until=self.simulation_time)
        
        # Print all events
        self.logger.print_events()
    
    def client_generator(self, env: simpy.Environment):
        """Generate clients over time."""
        # First client at t=0
        self.client_counter += 1
        client_id = self.client_counter
        arrival_time = 0.0
        
        # Log client generation
        self.logger.log_event(arrival_time, "client_generated", 
                             "client_generator", "ClientGenerator",
                             {"client_id": client_id, "arrival_time": arrival_time})
        
        # Try to pair with available employee
        self.try_pair_client(env, client_id, arrival_time)
        
        # Generate subsequent clients
        while True:
            # Calculate next inter-arrival time
            interval = bounded_normal(self.client_mean, self.client_stddev, 0, 5)
            interval = max(0.0, interval)
            
            # Wait for inter-arrival time
            yield env.timeout(interval)
            
            # Check if we're still within simulation time
            if env.now >= self.simulation_time:
                break
            
            # Generate client
            self.client_counter += 1
            client_id = self.client_counter
            arrival_time = env.now
            
            # Log client generation
            self.logger.log_event(arrival_time, "client_generated", 
                                 "client_generator", "ClientGenerator",
                                 {"client_id": client_id, "arrival_time": arrival_time})
            
            # Try to pair with available employee
            self.try_pair_client(env, client_id, arrival_time)
    
    def try_pair_client(self, env: simpy.Environment, client_id: int, 
                       arrival_time: float):
        """Try to pair a client with an available employee."""
        # Check for available employees
        available_employees = [eid for eid, available in 
                              self.employee_status.items() if available]
        
        if available_employees:
            # Pair with first available employee
            employee_id = available_employees[0]
            self.pair_client(env, client_id, employee_id, arrival_time)
        else:
            # Add to queue
            self.queue.append({
                "client_id": client_id,
                "arrival_time": arrival_time
            })
    
    def pair_client(self, env: simpy.Environment, client_id: int, 
                   employee_id: int, arrival_time: float):
        """Pair a client with an employee and start service."""
        paired_time = env.now
        
        # Mark employee as busy
        self.employee_status[employee_id] = False
        
        # Log pairing
        self.logger.log_event(paired_time, "client_paired", "queue", "Queue",
                             {"client_id": client_id, "employee_id": employee_id,
                              "paired_time": paired_time})
        
        # Store paired time for later
        self.paired_clients[client_id] = paired_time
        
        # Calculate service duration
        if employee_id == 1:
            service_duration = bounded_normal(self.employee_1_mean, 
                                             self.employee_1_stddev, 3, 3)
        else:
            service_duration = bounded_normal(self.employee_2_mean, 
                                             self.employee_2_stddev, 3, 3)
        
        # Schedule service completion
        env.process(self.service_completion(env, client_id, employee_id, 
                                           arrival_time, service_duration))
    
    def service_completion(self, env: simpy.Environment, client_id: int,
                          employee_id: int, arrival_time: float,
                          service_duration: float):
        """Handle service completion."""
        # Wait for service duration
        yield env.timeout(service_duration)
        
        # Check if we're still within simulation time
        if env.now > self.simulation_time:
            return
        
        # Log client served
        dispatched = env.now
        delay = dispatched - arrival_time
        
        self.logger.log_event(dispatched, "client_served", "employee",
                             f"Employee_{employee_id}",
                             {"client_id": client_id, "employee_id": employee_id,
                              "arrived": arrival_time, "dispatched": dispatched,
                              "delay": delay})
        
        # Mark employee as available
        self.employee_status[employee_id] = True
        
        # Log employee availability
        self.logger.log_event(dispatched, "employee_available", "employee",
                             f"Employee_{employee_id}",
                             {"employee_id": employee_id})
        
        # Check queue for waiting clients
        self.check_queue(env)
    
    def check_queue(self, env: simpy.Environment):
        """Check queue and pair waiting clients with available employees."""
        while self.queue:
            # Check for available employees
            available_employees = [eid for eid, available in 
                                  self.employee_status.items() if available]
            
            if not available_employees:
                break
            
            # Get next client from queue (FIFO)
            client_data = self.queue.pop(0)
            client_id = client_data["client_id"]
            arrival_time = client_data["arrival_time"]
            
            # Pair with first available employee
            employee_id = available_employees[0]
            self.pair_client(env, client_id, employee_id, arrival_time)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Store Cashier Simulation - Discrete Event Simulation"
    )
    
    parser.add_argument(
        "--simulation_time",
        type=str,
        default="00:05:00:000",
        help="Total simulation horizon in HH:MM:SS:mmm format"
    )
    
    parser.add_argument(
        "--client_mean",
        type=float,
        default=10.0,
        help="Mean inter-arrival time for clients"
    )
    
    parser.add_argument(
        "--client_stddev",
        type=float,
        default=5.0,
        help="Standard deviation of inter-arrival time for clients"
    )
    
    parser.add_argument(
        "--employee_1_mean",
        type=float,
        default=20.0,
        help="Mean service duration for employee 1"
    )
    
    parser.add_argument(
        "--employee_1_stddev",
        type=float,
        default=0.0,
        help="Standard deviation of service duration for employee 1"
    )
    
    parser.add_argument(
        "--employee_2_mean",
        type=float,
        default=30.0,
        help="Mean service duration for employee 2"
    )
    
    parser.add_argument(
        "--employee_2_stddev",
        type=float,
        default=4.0,
        help="Standard deviation of service duration for employee 2"
    )
    
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility"
    )
    
    args = parser.parse_args()
    
    # Parse simulation time
    simulation_time = parse_time(args.simulation_time)
    
    # Create and run simulation
    sim = StoreSimulation(
        simulation_time=simulation_time,
        client_mean=args.client_mean,
        client_stddev=args.client_stddev,
        employee_1_mean=args.employee_1_mean,
        employee_1_stddev=args.employee_1_stddev,
        employee_2_mean=args.employee_2_mean,
        employee_2_stddev=args.employee_2_stddev,
        seed=args.seed
    )
    
    sim.run()


if __name__ == "__main__":
    main()
