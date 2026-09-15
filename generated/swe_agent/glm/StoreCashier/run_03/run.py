#!/usr/bin/env python3
"""
Two-Employee Store Cashier Simulation

Simulates a store cashier system with one client generator, one FIFO queue,
and two employees using discrete event simulation.
"""

import argparse
import json
import random
import sys
from typing import Optional
import simpy


def parse_time_str(time_str: str) -> float:
    """Parse HH:MM:SS:mmm format to seconds."""
    parts = time_str.split(':')
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {time_str}")
    hours, minutes, seconds, milliseconds = map(int, parts)
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def format_time_str(time_seconds: float) -> str:
    """Format seconds to HH:MM:SS:mmm format."""
    total_ms = int(time_seconds * 1000)
    hours = total_ms // (3600 * 1000)
    remaining = total_ms % (3600 * 1000)
    minutes = remaining // (60 * 1000)
    remaining = remaining % (60 * 1000)
    seconds = remaining // 1000
    milliseconds = remaining % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"


def truncated_normal(mean: float, stddev: float, min_val: float, max_val: float) -> float:
    """Sample from a truncated normal distribution."""
    if stddev == 0:
        return mean
    while True:
        value = random.gauss(mean, stddev)
        if min_val <= value <= max_val:
            return value


class EventLogger:
    """Handles logging of simulation events in JSONL format."""
    
    def __init__(self, simulation_horizon: float):
        self.simulation_horizon = simulation_horizon
        self.events = []
    
    def log(self, time: float, event: str, entity_type: str, entity: str, payload: dict):
        """Log an event if it's within the simulation horizon."""
        if time <= self.simulation_horizon:
            self.events.append({
                "time": time,
                "time_str": format_time_str(time),
                "event": event,
                "entity_type": entity_type,
                "entity": entity,
                "payload": payload
            })
    
    def output(self):
        """Output all logged events in JSONL format."""
        for event in self.events:
            print(json.dumps(event))


class Client:
    """Represents a client in the system."""
    
    _id_counter = 1
    
    def __init__(self, arrival_time: float):
        self.id = Client._id_counter
        Client._id_counter += 1
        self.arrival_time = arrival_time
        self.paired_time: Optional[float] = None
        self.employee_id: Optional[int] = None


class StoreSimulation:
    """Main simulation class for the two-employee store cashier system."""
    
    def __init__(
        self,
        simulation_time_str: str,
        client_mean: float,
        client_stddev: float,
        employee_1_mean: float,
        employee_1_stddev: float,
        employee_2_mean: float,
        employee_2_stddev: float,
        seed: Optional[int] = None
    ):
        self.simulation_horizon = parse_time_str(simulation_time_str)
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.employee_1_mean = employee_1_mean
        self.employee_1_stddev = employee_1_stddev
        self.employee_2_mean = employee_2_mean
        self.employee_2_stddev = employee_2_stddev
        
        if seed is not None:
            random.seed(seed)
        
        self.logger = EventLogger(self.simulation_horizon)
        self.queue = []
        self.employees = {
            1: {"available": True, "current_client": None},
            2: {"available": True, "current_client": None}
        }
    
    def generate_client(self, env: simpy.Environment):
        """Generate clients over time."""
        # First client at t = 0.0
        yield env.timeout(0)
        
        while True:
            client = Client(env.now)
            self.logger.log(
                time=env.now,
                event="client_generated",
                entity_type="client_generator",
                entity="ClientGenerator",
                payload={"client_id": client.id, "arrival_time": client.arrival_time}
            )
            
            # Add to queue
            self.queue.append(client)
            
            # Try to pair with available employee
            self.try_pair_client(env)
            
            # Schedule next client
            max_interval = self.client_mean + 5 * self.client_stddev
            interval = truncated_normal(self.client_mean, self.client_stddev, 0, max_interval)
            yield env.timeout(interval)
    
    def try_pair_client(self, env: simpy.Environment):
        """Try to pair a waiting client with an available employee."""
        if not self.queue:
            return
        
        # Find available employees
        available_employees = [
            emp_id for emp_id, emp in self.employees.items()
            if emp["available"]
        ]
        
        if not available_employees:
            return
        
        # Get the first client in FIFO order
        client = self.queue.pop(0)
        
        # Assign to first available employee
        employee_id = available_employees[0]
        self.employees[employee_id]["available"] = False
        self.employees[employee_id]["current_client"] = client
        
        client.paired_time = env.now
        client.employee_id = employee_id
        
        self.logger.log(
            time=env.now,
            event="client_paired",
            entity_type="queue",
            entity="Queue",
            payload={
                "client_id": client.id,
                "employee_id": employee_id,
                "paired_time": client.paired_time
            }
        )
        
        # Start service
        env.process(self.serve_client(env, employee_id, client))
    
    def serve_client(self, env: simpy.Environment, employee_id: int, client: Client):
        """Serve a client."""
        # Determine service duration
        if employee_id == 1:
            mean = self.employee_1_mean
            stddev = self.employee_1_stddev
        else:
            mean = self.employee_2_mean
            stddev = self.employee_2_stddev
        
        min_duration = mean - 3 * stddev
        max_duration = mean + 3 * stddev
        duration = truncated_normal(mean, stddev, min_duration, max_duration)
        
        # Wait for service to complete
        yield env.timeout(duration)
        
        # Check if we're still within simulation horizon
        if env.now > self.simulation_horizon:
            return
        
        # Log client served event
        dispatched = env.now
        delay = dispatched - client.arrival_time
        
        self.logger.log(
            time=dispatched,
            event="client_served",
            entity_type="employee",
            entity=f"Employee_{employee_id}",
            payload={
                "client_id": client.id,
                "employee_id": employee_id,
                "arrived": client.arrival_time,
                "dispatched": dispatched,
                "delay": delay
            }
        )
        
        # Mark employee as available
        self.employees[employee_id]["available"] = True
        self.employees[employee_id]["current_client"] = None
        
        # Log employee available event
        self.logger.log(
            time=env.now,
            event="employee_available",
            entity_type="employee",
            entity=f"Employee_{employee_id}",
            payload={"employee_id": employee_id}
        )
        
        # Try to pair next client
        self.try_pair_client(env)
    
    def run(self):
        """Run the simulation."""
        env = simpy.Environment()
        
        # Log initial employee availability
        self.logger.log(
            time=0.0,
            event="employee_available",
            entity_type="employee",
            entity="Employee_1",
            payload={"employee_id": 1}
        )
        self.logger.log(
            time=0.0,
            event="employee_available",
            entity_type="employee",
            entity="Employee_2",
            payload={"employee_id": 2}
        )
        
        # Start client generator
        env.process(self.generate_client(env))
        
        # Run simulation
        env.run(until=self.simulation_horizon)
        
        # Output events
        self.logger.output()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Two-Employee Store Cashier Simulation"
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
        help="Standard deviation for client inter-arrival times (default: 5.0)"
    )
    
    parser.add_argument(
        "--employee_1_mean",
        type=float,
        default=20.0,
        help="Mean service time for Employee 1 (default: 20.0)"
    )
    
    parser.add_argument(
        "--employee_1_stddev",
        type=float,
        default=0.0,
        help="Standard deviation for Employee 1 service times (default: 0.0)"
    )
    
    parser.add_argument(
        "--employee_2_mean",
        type=float,
        default=30.0,
        help="Mean service time for Employee 2 (default: 30.0)"
    )
    
    parser.add_argument(
        "--employee_2_stddev",
        type=float,
        default=4.0,
        help="Standard deviation for Employee 2 service times (default: 4.0)"
    )
    
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility (optional)"
    )
    
    args = parser.parse_args()
    
    # Create and run simulation
    simulation = StoreSimulation(
        simulation_time_str=args.simulation_time,
        client_mean=args.client_mean,
        client_stddev=args.client_stddev,
        employee_1_mean=args.employee_1_mean,
        employee_1_stddev=args.employee_1_stddev,
        employee_2_mean=args.employee_2_mean,
        employee_2_stddev=args.employee_2_stddev,
        seed=args.seed
    )
    
    simulation.run()


if __name__ == "__main__":
    main()
