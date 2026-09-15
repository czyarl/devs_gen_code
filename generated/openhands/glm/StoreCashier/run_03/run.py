#!/usr/bin/env python3
"""Store Cashier Simulation - Two-Employee System"""

import argparse
import json
import random
from typing import List, Dict, Any
import simpy


class EventLogger:
    """Handles logging events in JSONL format."""
    
    def __init__(self):
        self.events: List[Dict[str, Any]] = []
    
    def log(self, time: float, event_type: str, entity_type: str, 
            entity: str, payload: Dict[str, Any]) -> None:
        """Log an event with the specified details."""
        time_str = self.format_time(time)
        event = {
            "time": time,
            "time_str": time_str,
            "event": event_type,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload
        }
        self.events.append(event)
    
    def format_time(self, time: float) -> str:
        """Format time as HH:MM:SS:mmm."""
        total_seconds = int(time)
        milliseconds = int((time - total_seconds) * 1000)
        
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"
    
    def print_events(self) -> None:
        """Print all events in JSONL format."""
        for event in self.events:
            print(json.dumps(event))


class StoreCashierSimulation:
    """Simulates a store cashier system with two employees."""
    
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
        self.env = simpy.Environment()
        self.client_counter = 0
        
        # Queue to hold waiting clients (FIFO) - using simple list
        self.waiting_queue: List[Dict[str, Any]] = []
        
        # Employee resources (each can serve one client at a time)
        self.employee_1 = simpy.Resource(self.env, capacity=1)
        self.employee_2 = simpy.Resource(self.env, capacity=1)
        
        # Track which employee is serving which client
        self.employee_assignments = {1: None, 2: None}
    
    def generate_client(self) -> None:
        """Generate clients over time."""
        # First client at t=0.0
        self.env.process(self.client_generator_process(0.0))
    
    def client_generator_process(self, first_delay: float = 0.0):
        """Process that generates clients."""
        yield self.env.timeout(first_delay)
        
        while True:
            # Check if we're still within simulation time
            if self.env.now >= self.simulation_time:
                break
            
            # Generate new client
            self.client_counter += 1
            client_id = self.client_counter
            arrival_time = self.env.now
            
            # Log client_generated event
            self.logger.log(
                time=arrival_time,
                event_type="client_generated",
                entity_type="client_generator",
                entity="ClientGenerator",
                payload={"client_id": client_id, "arrival_time": arrival_time}
            )
            
            # Add client to waiting queue
            self.waiting_queue.append({"client_id": client_id, "arrival_time": arrival_time})
            
            # Try to pair client with available employee
            self.try_pair_clients()
            
            # Schedule next client generation
            if self.env.now >= self.simulation_time:
                break
            
            interval = self.sample_client_interval()
            next_arrival = self.env.now + interval
            
            # Only schedule if within simulation time
            if next_arrival < self.simulation_time:
                yield self.env.timeout(interval)
            else:
                break
    
    def sample_client_interval(self) -> float:
        """Sample inter-arrival time for clients."""
        max_interval = self.client_mean + 5 * self.client_stddev
        # Sample from normal distribution and clamp to valid range
        interval = random.gauss(self.client_mean, self.client_stddev)
        return max(0.0, min(interval, max_interval))
    
    def sample_service_duration(self, employee_id: int) -> float:
        """Sample service duration for an employee."""
        if employee_id == 1:
            mean = self.employee_1_mean
            stddev = self.employee_1_stddev
        else:
            mean = self.employee_2_mean
            stddev = self.employee_2_stddev
        
        if stddev == 0:
            return mean
        
        min_duration = mean - 3 * stddev
        max_duration = mean + 3 * stddev
        duration = random.gauss(mean, stddev)
        return max(min_duration, min(duration, max_duration))
    
    def try_pair_clients(self):
        """Try to pair waiting clients with available employees."""
        # Check if there are waiting clients and available employees
        while True:
            # Check employee 1 availability (using employee_assignments, not resource count)
            if self.employee_assignments[1] is None:
                # Employee 1 is available
                if len(self.waiting_queue) > 0:
                    client = self.waiting_queue.pop(0)  # FIFO - pop from front
                    self.env.process(self.serve_client(client, 1))
                    continue
            
            # Check employee 2 availability (using employee_assignments, not resource count)
            if self.employee_assignments[2] is None:
                # Employee 2 is available
                if len(self.waiting_queue) > 0:
                    client = self.waiting_queue.pop(0)  # FIFO - pop from front
                    self.env.process(self.serve_client(client, 2))
                    continue
            
            break
    
    def serve_client(self, client: Dict[str, Any], employee_id: int):
        """Serve a client with the specified employee."""
        client_id = client["client_id"]
        arrival_time = client["arrival_time"]
        
        # Request the employee resource
        if employee_id == 1:
            resource = self.employee_1
            entity_name = "Employee_1"
        else:
            resource = self.employee_2
            entity_name = "Employee_2"
        
        # Mark employee as busy immediately (before acquiring resource)
        self.employee_assignments[employee_id] = client_id
        
        with resource.request() as req:
            yield req
            
            paired_time = self.env.now
            
            # Log client_paired event
            self.logger.log(
                time=paired_time,
                event_type="client_paired",
                entity_type="queue",
                entity="Queue",
                payload={
                    "client_id": client_id,
                    "employee_id": employee_id,
                    "paired_time": paired_time
                }
            )
            
            # Sample service duration
            service_duration = self.sample_service_duration(employee_id)
            
            # Simulate service time
            yield self.env.timeout(service_duration)
            
            # Check if service completion is within simulation time
            if self.env.now <= self.simulation_time:
                dispatched = self.env.now
                delay = dispatched - arrival_time
                
                # Log client_served event
                self.logger.log(
                    time=dispatched,
                    event_type="client_served",
                    entity_type="employee",
                    entity=entity_name,
                    payload={
                        "client_id": client_id,
                        "employee_id": employee_id,
                        "arrived": arrival_time,
                        "dispatched": dispatched,
                        "delay": delay
                    }
                )
            
            # Mark employee as available
            self.employee_assignments[employee_id] = None
            
            # Only log employee_available if within simulation time
            if self.env.now <= self.simulation_time:
                self.logger.log(
                    time=self.env.now,
                    event_type="employee_available",
                    entity_type="employee",
                    entity=entity_name,
                    payload={"employee_id": employee_id}
                )
            
            # Try to pair more clients
            self.try_pair_clients()
    
    def initialize_employees(self):
        """Initialize employees as available at t=0.0."""
        # Log initial availability for both employees
        self.logger.log(
            time=0.0,
            event_type="employee_available",
            entity_type="employee",
            entity="Employee_1",
            payload={"employee_id": 1}
        )
        
        self.logger.log(
            time=0.0,
            event_type="employee_available",
            entity_type="employee",
            entity="Employee_2",
            payload={"employee_id": 2}
        )
    
    def run(self):
        """Run the simulation."""
        # Initialize employees
        self.initialize_employees()
        
        # Start client generation
        self.generate_client()
        
        # Run simulation
        self.env.run(until=self.simulation_time)
        
        # Print all events
        self.logger.print_events()


def parse_time(time_str: str) -> float:
    """Parse time string in HH:MM:SS:mmm format to seconds."""
    parts = time_str.split(":")
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {time_str}")
    
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Store Cashier Simulation")
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
        help="Mean service time for employee 1"
    )
    parser.add_argument(
        "--employee_1_stddev",
        type=float,
        default=0.0,
        help="Standard deviation of service time for employee 1"
    )
    parser.add_argument(
        "--employee_2_mean",
        type=float,
        default=30.0,
        help="Mean service time for employee 2"
    )
    parser.add_argument(
        "--employee_2_stddev",
        type=float,
        default=4.0,
        help="Standard deviation of service time for employee 2"
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
    sim = StoreCashierSimulation(
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
