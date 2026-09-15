#!/usr/bin/env python3
"""
Two-Employee Store Cashier Simulation

A discrete event simulation of a store cashier system with one client generator,
one FIFO queue, and two employees.
"""

import argparse
import json
import random
import sys
from typing import List, Optional
import simpy


def parse_time_str(time_str: str) -> float:
    """Parse HH:MM:SS:mmm format to seconds."""
    parts = time_str.split(':')
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {time_str}")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def format_time_str(time: float) -> str:
    """Format seconds to HH:MM:SS:mmm format."""
    total_ms = int(time * 1000 + 0.5)
    hours = total_ms // (3600 * 1000)
    remaining = total_ms % (3600 * 1000)
    minutes = remaining // (60 * 1000)
    remaining = remaining % (60 * 1000)
    seconds = remaining // 1000
    milliseconds = remaining % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"


def clamp_normal(mean: float, stddev: float, min_val: float, max_val: float) -> float:
    """Sample from normal distribution and clamp to range."""
    if stddev == 0:
        return mean
    value = random.gauss(mean, stddev)
    return max(min_val, min(max_val, value))


class EventLogger:
    """Logger for simulation events in JSONL format."""
    
    def __init__(self):
        self.events: List[dict] = []
    
    def log(self, time: float, event: str, entity_type: str, entity: str, payload: dict):
        """Log an event."""
        self.events.append({
            "time": time,
            "time_str": format_time_str(time),
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


class StoreSimulation:
    """Main simulation class for the two-employee store."""
    
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
        if seed is not None:
            random.seed(seed)
        
        self.simulation_time = simulation_time
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.employee_1_mean = employee_1_mean
        self.employee_1_stddev = employee_1_stddev
        self.employee_2_mean = employee_2_mean
        self.employee_2_stddev = employee_2_stddev
        
        self.logger = EventLogger()
        self.client_counter = 0
        self.queue: List[Client] = []
        
        # Employee states
        self.employee_1_busy = False
        self.employee_2_busy = False
        self.employee_1_current_client: Optional[Client] = None
        self.employee_2_current_client: Optional[Client] = None
        
        # Create SimPy environment
        self.env = simpy.Environment()
    
    def get_next_client_id(self) -> int:
        """Get next sequential client ID."""
        self.client_counter += 1
        return self.client_counter
    
    def log_employee_available(self, employee_id: int, time: float):
        """Log employee available event."""
        entity = f"Employee_{employee_id}"
        self.logger.log(
            time=time,
            event="employee_available",
            entity_type="employee",
            entity=entity,
            payload={"employee_id": employee_id}
        )
    
    def log_client_generated(self, client_id: int, arrival_time: float):
        """Log client generated event."""
        self.logger.log(
            time=arrival_time,
            event="client_generated",
            entity_type="client_generator",
            entity="ClientGenerator",
            payload={"client_id": client_id, "arrival_time": arrival_time}
        )
    
    def log_client_paired(self, client_id: int, employee_id: int, paired_time: float):
        """Log client paired event."""
        self.logger.log(
            time=paired_time,
            event="client_paired",
            entity_type="queue",
            entity="Queue",
            payload={"client_id": client_id, "employee_id": employee_id, "paired_time": paired_time}
        )
    
    def log_client_served(self, client_id: int, employee_id: int, arrived: float, dispatched: float):
        """Log client served event."""
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
        
        # Try Employee 1 first
        if not self.employee_1_busy:
            client = self.queue.pop(0)
            self.employee_1_busy = True
            self.employee_1_current_client = client
            client.paired_time = self.env.now
            client.employee_id = 1
            self.log_client_paired(client.client_id, 1, self.env.now)
            
            # Schedule service completion
            duration = clamp_normal(
                self.employee_1_mean,
                self.employee_1_stddev,
                self.employee_1_mean - 3 * self.employee_1_stddev,
                self.employee_1_mean + 3 * self.employee_1_stddev
            )
            self.env.process(self.complete_service(1, duration))
            return
        
        # Try Employee 2
        if not self.employee_2_busy:
            client = self.queue.pop(0)
            self.employee_2_busy = True
            self.employee_2_current_client = client
            client.paired_time = self.env.now
            client.employee_id = 2
            self.log_client_paired(client.client_id, 2, self.env.now)
            
            # Schedule service completion
            duration = clamp_normal(
                self.employee_2_mean,
                self.employee_2_stddev,
                self.employee_2_mean - 3 * self.employee_2_stddev,
                self.employee_2_mean + 3 * self.employee_2_stddev
            )
            self.env.process(self.complete_service(2, duration))
    
    def complete_service(self, employee_id: int, duration: float):
        """Process service completion for an employee."""
        yield self.env.timeout(duration)
        
        completion_time = self.env.now
        
        # Only process if within simulation horizon
        if completion_time > self.simulation_time:
            return
        
        # Get the client being served
        if employee_id == 1:
            client = self.employee_1_current_client
            self.employee_1_busy = False
            self.employee_1_current_client = None
        else:
            client = self.employee_2_current_client
            self.employee_2_busy = False
            self.employee_2_current_client = None
        
        if client is not None:
            self.log_client_served(
                client.client_id,
                employee_id,
                client.arrival_time,
                completion_time
            )
        
        # Log employee available
        self.log_employee_available(employee_id, completion_time)
        
        # Try to pair next client
        self.try_pair_client()
    
    def client_generator_process(self):
        """Generate clients over time."""
        # First client at t = 0.0
        client_id = self.get_next_client_id()
        client = Client(client_id, 0.0)
        self.queue.append(client)
        self.log_client_generated(client_id, 0.0)
        self.try_pair_client()
        
        # Generate subsequent clients
        while True:
            # Sample inter-arrival time
            interval = clamp_normal(
                self.client_mean,
                self.client_stddev,
                0.0,
                self.client_mean + 5 * self.client_stddev
            )
            
            yield self.env.timeout(interval)
            
            arrival_time = self.env.now
            
            # Stop if beyond simulation horizon
            if arrival_time > self.simulation_time:
                break
            
            client_id = self.get_next_client_id()
            client = Client(client_id, arrival_time)
            self.queue.append(client)
            self.log_client_generated(client_id, arrival_time)
            self.try_pair_client()
    
    def run(self):
        """Run the simulation."""
        # Log initial employee availability at t = 0.0
        self.log_employee_available(1, 0.0)
        self.log_employee_available(2, 0.0)
        
        # Start client generator
        self.env.process(self.client_generator_process())
        
        # Run simulation
        self.env.run(until=self.simulation_time)
        
        # Print all events
        self.logger.print_events()


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
        help="Standard deviation of inter-arrival time for clients (default: 5.0)"
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
        help="Standard deviation of service time for Employee 1 (default: 0.0)"
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
        help="Standard deviation of service time for Employee 2 (default: 4.0)"
    )
    
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility (optional)"
    )
    
    args = parser.parse_args()
    
    # Parse simulation time
    simulation_time = parse_time_str(args.simulation_time)
    
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
