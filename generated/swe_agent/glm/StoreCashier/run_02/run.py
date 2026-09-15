#!/usr/bin/env python3
"""
Two-Employee Store Cashier Simulation System

Simulates a store cashier system with one client generator, one FIFO queue,
and two employees using discrete event simulation.
"""

import argparse
import json
import random
import sys
from typing import Dict, List, Optional
import simpy


def parse_time_str(time_str: str) -> float:
    """Parse HH:MM:SS:mmm format to seconds."""
    parts = time_str.split(':')
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {time_str}")
    hours, minutes, seconds, milliseconds = map(int, parts)
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def format_time_str(time: float) -> str:
    """Format seconds to HH:MM:SS:mmm format."""
    total_ms = int(time * 1000)
    hours = total_ms // (3600 * 1000)
    remaining = total_ms % (3600 * 1000)
    minutes = remaining // (60 * 1000)
    remaining = remaining % (60 * 1000)
    seconds = remaining // 1000
    milliseconds = remaining % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"


class EventLogger:
    """Handles logging of simulation events in JSONL format."""
    
    def __init__(self):
        self.events: List[dict] = []
    
    def log(self, time: float, event: str, entity_type: str, entity: str, payload: dict):
        """Log an event."""
        event_obj = {
            "time": float(time),
            "time_str": format_time_str(time),
            "event": event,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload
        }
        self.events.append(event_obj)
    
    def print_events(self):
        """Print all events to stdout in JSONL format."""
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
    """Main simulation class for the two-employee store cashier system."""
    
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
        
        self.logger = EventLogger()
        self.env = simpy.Environment()
        
        # Client tracking
        self.next_client_id = 1
        self.clients: Dict[int, Client] = {}
        self.waiting_queue: List[Client] = []
        
        # Employee resources (each can serve one client at a time)
        self.employee_1 = simpy.Resource(self.env, capacity=1)
        self.employee_2 = simpy.Resource(self.env, capacity=1)
        
        # Track employee availability
        self.employee_1_available = True
        self.employee_2_available = True
        
        # Track which employee is serving which client
        self.employee_1_client: Optional[Client] = None
        self.employee_2_client: Optional[Client] = None
    
    def sample_client_interval(self) -> float:
        """Sample client inter-arrival time from normal distribution."""
        interval = random.gauss(self.client_mean, self.client_stddev)
        # Clamp to valid range: 0 <= interval <= client_mean + 5 * client_stddev
        max_interval = self.client_mean + 5 * self.client_stddev
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
        
        duration = random.gauss(mean, stddev)
        # Clamp to valid range: mean - 3*stddev <= duration <= mean + 3*stddev
        min_duration = mean - 3 * stddev
        max_duration = mean + 3 * stddev
        return max(min_duration, min(duration, max_duration))
    
    def log_employee_available(self, employee_id: int, time: float):
        """Log an employee_available event."""
        entity = f"Employee_{employee_id}"
        self.logger.log(
            time=float(time),
            event="employee_available",
            entity_type="employee",
            entity=entity,
            payload={"employee_id": employee_id}
        )
    
    def log_client_generated(self, client_id: int, arrival_time: float):
        """Log a client_generated event."""
        self.logger.log(
            time=float(arrival_time),
            event="client_generated",
            entity_type="client_generator",
            entity="ClientGenerator",
            payload={"client_id": client_id, "arrival_time": float(arrival_time)}
        )
    
    def log_client_paired(self, client_id: int, employee_id: int, paired_time: float):
        """Log a client_paired event."""
        self.logger.log(
            time=float(paired_time),
            event="client_paired",
            entity_type="queue",
            entity="Queue",
            payload={"client_id": client_id, "employee_id": employee_id, "paired_time": float(paired_time)}
        )
    
    def log_client_served(self, client_id: int, employee_id: int, arrived: float, dispatched: float, delay: float):
        """Log a client_served event."""
        entity = f"Employee_{employee_id}"
        self.logger.log(
            time=float(dispatched),
            event="client_served",
            entity_type="employee",
            entity=entity,
            payload={
                "client_id": client_id,
                "employee_id": employee_id,
                "arrived": float(arrived),
                "dispatched": float(dispatched),
                "delay": float(delay)
            }
        )
    
    def try_pair_client(self):
        """Try to pair a waiting client with an available employee."""
        if not self.waiting_queue:
            return
        
        # Get the next client in FIFO order
        client = self.waiting_queue[0]
        
        # Try to pair with employee 1
        if self.employee_1_available and self.employee_1_client is None:
            self.waiting_queue.pop(0)
            self.pair_client_with_employee(client, 1)
            return
        
        # Try to pair with employee 2
        if self.employee_2_available and self.employee_2_client is None:
            self.waiting_queue.pop(0)
            self.pair_client_with_employee(client, 2)
            return
    
    def pair_client_with_employee(self, client: Client, employee_id: int):
        """Pair a client with an employee and start service."""
        paired_time = self.env.now
        client.paired_time = paired_time
        client.employee_id = employee_id
        
        self.log_client_paired(client.client_id, employee_id, paired_time)
        
        # Mark employee as busy
        if employee_id == 1:
            self.employee_1_available = False
            self.employee_1_client = client
        else:
            self.employee_2_available = False
            self.employee_2_client = client
        
        # Start service process
        self.env.process(self.service_client(client, employee_id))
    
    def service_client(self, client: Client, employee_id: int):
        """Service a client and mark employee as available when done."""
        service_duration = self.sample_service_duration(employee_id)
        
        yield self.env.timeout(service_duration)
        
        # Check if we're still within simulation time
        if self.env.now > self.simulation_time:
            return
        
        # Calculate delay
        delay = self.env.now - client.arrival_time
        
        # Log client_served event
        self.log_client_served(
            client_id=client.client_id,
            employee_id=employee_id,
            arrived=client.arrival_time,
            dispatched=self.env.now,
            delay=delay
        )
        
        # Mark employee as available
        if employee_id == 1:
            self.employee_1_available = True
            self.employee_1_client = None
        else:
            self.employee_2_available = True
            self.employee_2_client = None
        
        # Log employee_available event
        self.log_employee_available(employee_id, self.env.now)
        
        # Try to pair next waiting client
        self.try_pair_client()
    
    def client_generator_process(self):
        """Generate clients over time."""
        # First client at t = 0.0
        arrival_time = 0.0
        
        while True:
            # Check if we're past simulation time
            if arrival_time > self.simulation_time:
                break
            
            # Generate client
            client = Client(self.next_client_id, arrival_time)
            self.clients[self.next_client_id] = client
            self.log_client_generated(self.next_client_id, arrival_time)
            self.next_client_id += 1
            
            # Add to waiting queue
            self.waiting_queue.append(client)
            
            # Try to pair immediately
            self.try_pair_client()
            
            # Schedule next client
            interval = self.sample_client_interval()
            arrival_time += interval
            
            # Wait for the inter-arrival time
            yield self.env.timeout(interval)
    
    def run(self):
        """Run the simulation."""
        # Log initial employee availability at t = 0.0
        self.log_employee_available(1, 0.0)
        self.log_employee_available(2, 0.0)
        
        # Start client generator
        self.env.process(self.client_generator_process())
        
        # Run simulation
        self.env.run(until=self.simulation_time)
        
        # Filter out events that occurred after simulation time
        self.logger.events = [
            e for e in self.logger.events
            if e["time"] <= self.simulation_time
        ]
        
        # Print events
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
        help="Mean client inter-arrival time in seconds (default: 10.0)"
    )
    
    parser.add_argument(
        "--client_stddev",
        type=float,
        default=5.0,
        help="Standard deviation of client inter-arrival time in seconds (default: 5.0)"
    )
    
    parser.add_argument(
        "--employee_1_mean",
        type=float,
        default=20.0,
        help="Mean service time for employee 1 in seconds (default: 20.0)"
    )
    
    parser.add_argument(
        "--employee_1_stddev",
        type=float,
        default=0.0,
        help="Standard deviation of service time for employee 1 in seconds (default: 0.0)"
    )
    
    parser.add_argument(
        "--employee_2_mean",
        type=float,
        default=30.0,
        help="Mean service time for employee 2 in seconds (default: 30.0)"
    )
    
    parser.add_argument(
        "--employee_2_stddev",
        type=float,
        default=4.0,
        help="Standard deviation of service time for employee 2 in seconds (default: 4.0)"
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
