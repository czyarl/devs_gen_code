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
from typing import Dict, List, Optional
import simpy


def parse_time_str(time_str: str) -> float:
    """Parse time string in HH:MM:SS:mmm format to seconds."""
    parts = time_str.split(':')
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {time_str}")
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def format_time_str(time: float) -> str:
    """Format time in seconds to HH:MM:SS:mmm format."""
    total_ms = int(time * 1000)
    hours = total_ms // (3600 * 1000)
    remaining_ms = total_ms % (3600 * 1000)
    minutes = remaining_ms // (60 * 1000)
    remaining_ms = remaining_ms % (60 * 1000)
    seconds = remaining_ms // 1000
    milliseconds = remaining_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"


class EventLogger:
    """Logger for simulation events in JSONL format."""
    
    def __init__(self):
        self.events: List[dict] = []
    
    def log(self, time: float, event: str, entity_type: str, entity: str, payload: dict):
        """Log an event."""
        event_obj = {
            "time": time,
            "time_str": format_time_str(time),
            "event": event,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload
        }
        self.events.append(event_obj)
    
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
        self.client_counter = 0
        self.queue: List[Client] = []
        
        # Track employee status
        self.employee_1_busy = False
        self.employee_2_busy = False
        self.employee_1_current_client: Optional[Client] = None
        self.employee_2_current_client: Optional[Client] = None
        
        # Create SimPy environment
        self.env = simpy.Environment()
    
    def sample_inter_arrival_time(self) -> float:
        """Sample inter-arrival time from normal distribution within allowed range."""
        max_interval = self.client_mean + 5 * self.client_stddev
        while True:
            interval = random.gauss(self.client_mean, self.client_stddev)
            if 0 <= interval <= max_interval:
                return interval
    
    def sample_service_duration(self, employee_id: int) -> float:
        """Sample service duration for an employee within allowed range."""
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
        
        while True:
            duration = random.gauss(mean, stddev)
            if min_duration <= duration <= max_duration:
                return duration
    
    def log_employee_available(self, employee_id: int):
        """Log employee_available event."""
        if employee_id == 1:
            entity = "Employee_1"
        else:
            entity = "Employee_2"
        
        self.logger.log(
            time=self.env.now,
            event="employee_available",
            entity_type="employee",
            entity=entity,
            payload={"employee_id": employee_id}
        )
    
    def log_client_generated(self, client_id: int, arrival_time: float):
        """Log client_generated event."""
        self.logger.log(
            time=arrival_time,
            event="client_generated",
            entity_type="client_generator",
            entity="ClientGenerator",
            payload={"client_id": client_id, "arrival_time": arrival_time}
        )
    
    def log_client_paired(self, client_id: int, employee_id: int, paired_time: float):
        """Log client_paired event."""
        self.logger.log(
            time=paired_time,
            event="client_paired",
            entity_type="queue",
            entity="Queue",
            payload={"client_id": client_id, "employee_id": employee_id, "paired_time": paired_time}
        )
    
    def log_client_served(self, client_id: int, employee_id: int, arrived: float, dispatched: float):
        """Log client_served event."""
        delay = dispatched - arrived
        if employee_id == 1:
            entity = "Employee_1"
        else:
            entity = "Employee_2"
        
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
        
        # Check if employee 1 is available
        if not self.employee_1_busy:
            client = self.queue.pop(0)  # FIFO - get first client
            client.paired_time = self.env.now
            client.employee_id = 1
            self.employee_1_busy = True
            self.employee_1_current_client = client
            
            self.log_client_paired(client.client_id, 1, self.env.now)
            
            # Schedule service completion
            service_duration = self.sample_service_duration(1)
            self.env.process(self.complete_service(1, service_duration))
            return
        
        # Check if employee 2 is available
        if not self.employee_2_busy:
            client = self.queue.pop(0)  # FIFO - get first client
            client.paired_time = self.env.now
            client.employee_id = 2
            self.employee_2_busy = True
            self.employee_2_current_client = client
            
            self.log_client_paired(client.client_id, 2, self.env.now)
            
            # Schedule service completion
            service_duration = self.sample_service_duration(2)
            self.env.process(self.complete_service(2, service_duration))
    
    def complete_service(self, employee_id: int, duration: float):
        """Process service completion for an employee."""
        # Wait for service duration
        yield self.env.timeout(duration)
        
        # Check if we're past simulation time
        if self.env.now > self.simulation_time:
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
            # Log client_served event
            self.log_client_served(
                client.client_id,
                employee_id,
                client.arrival_time,
                self.env.now
            )
            
            # Log employee_available event
            self.log_employee_available(employee_id)
            
            # Try to pair next client
            self.try_pair_client()
    
    def client_generator_process(self):
        """Generate clients over time."""
        # First client at t = 0.0
        self.client_counter += 1
        client = Client(self.client_counter, self.env.now)
        self.log_client_generated(self.client_counter, self.env.now)
        self.queue.append(client)
        self.try_pair_client()
        
        # Generate subsequent clients
        while True:
            inter_arrival = self.sample_inter_arrival_time()
            next_arrival_time = self.env.now + inter_arrival
            
            # Stop if next arrival would be past simulation time
            if next_arrival_time > self.simulation_time:
                break
            
            yield self.env.timeout(inter_arrival)
            
            # Check if we're past simulation time
            if self.env.now > self.simulation_time:
                break
            
            self.client_counter += 1
            client = Client(self.client_counter, self.env.now)
            self.log_client_generated(self.client_counter, self.env.now)
            self.queue.append(client)
            self.try_pair_client()
    
    def run(self):
        """Run the simulation."""
        # Log initial employee availability
        self.log_employee_available(1)
        self.log_employee_available(2)
        
        # Start client generator
        self.env.process(self.client_generator_process())
        
        # Run simulation
        self.env.run(until=self.simulation_time)
        
        # Print all events
        self.logger.print_events()


def parse_arguments():
    """Parse command line arguments."""
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
        help="Mean inter-arrival time for clients in seconds (default: 10.0)"
    )
    
    parser.add_argument(
        "--client_stddev",
        type=float,
        default=5.0,
        help="Standard deviation of inter-arrival time for clients in seconds (default: 5.0)"
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
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_arguments()
    
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
