#!/usr/bin/env python3
"""
Store Cashier Discrete Event Simulation

Simulates a store cashier system with one client generator, one FIFO queue,
and two employees serving clients.
"""

import argparse
import json
import random
from typing import Dict, List, Optional
import simpy


def format_time(time_seconds: float) -> str:
    """Format simulation time in HH:MM:SS:mmm format."""
    total_millis = int(time_seconds * 1000)
    hours = total_millis // (3600 * 1000)
    remaining = total_millis % (3600 * 1000)
    minutes = remaining // (60 * 1000)
    remaining = remaining % (60 * 1000)
    seconds = remaining // 1000
    millis = remaining % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{millis:03d}"


def parse_time(time_str: str) -> float:
    """Parse time string HH:MM:SS:mmm to seconds."""
    parts = time_str.split(":")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    millis = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def clamp_normal(mean: float, stddev: float, min_val: float, max_val: float) -> float:
    """Sample from normal distribution and clamp to range."""
    if stddev == 0:
        return mean
    value = random.gauss(mean, stddev)
    return max(min_val, min(max_val, value))


class EventLogger:
    """Handles logging events in JSONL format."""
    
    def __init__(self):
        self.events: List[dict] = []
    
    def log(self, time: float, event: str, entity_type: str, entity: str, payload: dict):
        """Log an event."""
        self.events.append({
            "time": time,
            "time_str": format_time(time),
            "event": event,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload
        })
    
    def print_events(self):
        """Print all events in JSONL format."""
        for event in self.events:
            print(json.dumps(event))


class Client:
    """Represents a client in the system."""
    
    def __init__(self, client_id: int, arrival_time: float):
        self.client_id = client_id
        self.arrival_time = arrival_time
        self.paired_time: Optional[float] = None
        self.employee_id: Optional[int] = None


class StoreCashierSimulation:
    """Main simulation class for the store cashier system."""
    
    def __init__(
        self,
        simulation_time: float,
        client_mean: float,
        client_stddev: float,
        employee_1_mean: float,
        employee_1_stddev: float,
        employee_2_mean: float,
        employee_2_stddev: float,
        seed: Optional[int] = None
    ):
        self.simulation_time = simulation_time
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.employee_1_mean = employee_1_mean
        self.employee_1_stddev = employee_1_stddev
        self.employee_2_mean = employee_2_mean
        self.employee_2_stddev = employee_2_stddev
        
        if seed is not None:
            random.seed(seed)
        
        self.env = simpy.Environment()
        self.logger = EventLogger()
        
        # Queue for waiting clients (FIFO)
        self.queue: List[Client] = []
        
        # Employee availability tracking
        self.employee_available = {1: True, 2: True}
        
        # Client tracking
        self.client_counter = 0
        self.clients: Dict[int, Client] = {}
        
        # Track paired clients for service completion
        self.employee_current_client: Dict[int, Optional[Client]] = {1: None, 2: None}
    
    def emit_employee_available(self, employee_id: int, time: float):
        """Emit employee_available event."""
        entity = f"Employee_{employee_id}"
        self.logger.log(
            time=time,
            event="employee_available",
            entity_type="employee",
            entity=entity,
            payload={"employee_id": employee_id}
        )
    
    def emit_client_generated(self, client_id: int, arrival_time: float):
        """Emit client_generated event."""
        self.logger.log(
            time=arrival_time,
            event="client_generated",
            entity_type="client_generator",
            entity="ClientGenerator",
            payload={"client_id": client_id, "arrival_time": arrival_time}
        )
    
    def emit_client_paired(self, client_id: int, employee_id: int, paired_time: float):
        """Emit client_paired event."""
        self.logger.log(
            time=paired_time,
            event="client_paired",
            entity_type="queue",
            entity="Queue",
            payload={"client_id": client_id, "employee_id": employee_id, "paired_time": paired_time}
        )
    
    def emit_client_served(self, client_id: int, employee_id: int, arrived: float, dispatched: float):
        """Emit client_served event."""
        delay = dispatched - arrived
        entity = f"Employee_{employee_id}"
        self.logger.log(
            time=dispatched,
            event="client_served",
            entity_type="employee",
            entity=entity,
            payload={
                "client_id": client_id,
                "employee_id": employee_id,
                "arrived": arrived,
                "dispatched": dispatched,
                "delay": delay
            }
        )
    
    def try_pair_client(self):
        """Try to pair a waiting client with an available employee."""
        if not self.queue:
            return
        
        # Find available employees
        available_employees = [
            emp_id for emp_id, available in self.employee_available.items()
            if available and self.employee_current_client[emp_id] is None
        ]
        
        if not available_employees:
            return
        
        # Get the first client in FIFO order
        client = self.queue.pop(0)
        
        # Assign to first available employee
        employee_id = available_employees[0]
        
        # Update client and employee state
        client.paired_time = self.env.now
        client.employee_id = employee_id
        self.employee_available[employee_id] = False
        self.employee_current_client[employee_id] = client
        
        # Emit client_paired event
        self.emit_client_paired(client.client_id, employee_id, self.env.now)
        
        # Schedule service completion
        self.env.process(self.serve_client(employee_id, client))
    
    def serve_client(self, employee_id: int, client: Client):
        """Process serving a client by an employee."""
        # Determine service duration
        if employee_id == 1:
            mean = self.employee_1_mean
            stddev = self.employee_1_stddev
        else:
            mean = self.employee_2_mean
            stddev = self.employee_2_stddev
        
        min_duration = mean - 3 * stddev
        max_duration = mean + 3 * stddev
        service_duration = clamp_normal(mean, stddev, min_duration, max_duration)
        
        # Wait for service to complete
        yield self.env.timeout(service_duration)
        
        # Check if we're still within simulation time
        if self.env.now > self.simulation_time:
            return
        
        # Emit client_served event
        self.emit_client_served(
            client_id=client.client_id,
            employee_id=employee_id,
            arrived=client.arrival_time,
            dispatched=self.env.now
        )
        
        # Update employee state
        self.employee_current_client[employee_id] = None
        self.employee_available[employee_id] = True
        
        # Emit employee_available event
        self.emit_employee_available(employee_id, self.env.now)
        
        # Try to pair next client
        self.try_pair_client()
    
    def client_generator_process(self):
        """Generate clients over time."""
        while True:
            # Check if we're still within simulation time
            if self.env.now >= self.simulation_time:
                break
            
            # Generate new client
            self.client_counter += 1
            client_id = self.client_counter
            arrival_time = self.env.now
            
            client = Client(client_id, arrival_time)
            self.clients[client_id] = client
            
            # Emit client_generated event
            self.emit_client_generated(client_id, arrival_time)
            
            # Add client to queue
            self.queue.append(client)
            
            # Try to pair client with available employee
            self.try_pair_client()
            
            # Calculate next inter-arrival time
            max_interval = self.client_mean + 5 * self.client_stddev
            next_interval = clamp_normal(
                self.client_mean,
                self.client_stddev,
                0.0,
                max_interval
            )
            
            # Wait for next client
            yield self.env.timeout(next_interval)
    
    def run(self):
        """Run the simulation."""
        # Emit initial employee availability events
        self.emit_employee_available(1, 0.0)
        self.emit_employee_available(2, 0.0)
        
        # Start client generator
        self.env.process(self.client_generator_process())
        
        # Run simulation
        self.env.run(until=self.simulation_time)
        
        # Print all events
        self.logger.print_events()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Store Cashier Discrete Event Simulation"
    )
    
    parser.add_argument(
        "--simulation_time",
        type=str,
        default="00:05:00:000",
        help="Total simulation horizon in HH:MM:SS:mmm format (default: 00:05:00:000)"
    )
    
    parser.add_argument(
        "--client_mean",
        type=float,
        default=10.0,
        help="Mean inter-arrival time for clients (default: 10.0)"
    )
    
    parser.add_argument(
        "--client_stddev",
        type=float,
        default=5.0,
        help="Standard deviation of inter-arrival time for clients (default: 5.0)"
    )
    
    parser.add_argument(
        "--employee_1_mean",
        type=float,
        default=20.0,
        help="Mean service time for employee 1 (default: 20.0)"
    )
    
    parser.add_argument(
        "--employee_1_stddev",
        type=float,
        default=0.0,
        help="Standard deviation of service time for employee 1 (default: 0.0)"
    )
    
    parser.add_argument(
        "--employee_2_mean",
        type=float,
        default=30.0,
        help="Mean service time for employee 2 (default: 30.0)"
    )
    
    parser.add_argument(
        "--employee_2_stddev",
        type=float,
        default=4.0,
        help="Standard deviation of service time for employee 2 (default: 4.0)"
    )
    
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility (optional)"
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
