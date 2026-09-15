#!/usr/bin/env python3
"""
Two-Employee Store Cashier Simulation

Discrete event simulation of a store cashier system with one client generator,
one FIFO queue, and two employees serving clients.
"""

import argparse
import random
import json
import math
from typing import Optional
import simpy


def parse_time_str(time_str: str) -> float:
    """Parse HH:MM:SS:mmm format to seconds."""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
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


def clamp_normal(mean: float, stddev: float, min_val: float, max_val: float) -> float:
    """Sample from normal distribution and clamp to range."""
    if stddev == 0:
        return mean
    value = random.gauss(mean, stddev)
    return max(min_val, min(max_val, value))


class EventLogger:
    """Handles JSONL event logging."""
    
    def __init__(self):
        self.events = []
    
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
    
    def flush(self):
        """Print all events in order."""
        for event in self.events:
            print(json.dumps(event))


class StoreCashierSimulation:
    """Main simulation class."""
    
    def __init__(self, simulation_time: float, client_mean: float, client_stddev: float,
                 employee_1_mean: float, employee_1_stddev: float,
                 employee_2_mean: float, employee_2_stddev: float,
                 seed: Optional[int] = None):
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
        
        # Client tracking
        self.next_client_id = 1
        self.client_arrival_times = {}  # client_id -> arrival_time
        self.client_paired_times = {}  # client_id -> paired_time
        
        # Queue (FIFO)
        self.waiting_queue = []  # List of client_ids in arrival order
        
        # Employee availability
        self.employee_1_available = True
        self.employee_2_available = True
    
    def emit_employee_available(self, employee_id: int, time: float):
        """Emit employee_available event."""
        employee_name = f"Employee_{employee_id}"
        self.logger.log(
            time=time,
            event="employee_available",
            entity_type="employee",
            entity=employee_name,
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
    
    def emit_client_served(self, client_id: int, employee_id: int, arrived: float, 
                          dispatched: float, delay: float):
        """Emit client_served event."""
        employee_name = f"Employee_{employee_id}"
        self.logger.log(
            time=dispatched,
            event="client_served",
            entity_type="employee",
            entity=employee_name,
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
        if not self.waiting_queue:
            return
        
        if self.employee_1_available:
            client_id = self.waiting_queue.pop(0)
            self.employee_1_available = False
            paired_time = self.env.now
            self.client_paired_times[client_id] = paired_time
            self.emit_client_paired(client_id, 1, paired_time)
            self.env.process(self.serve_client(client_id, 1))
        elif self.employee_2_available:
            client_id = self.waiting_queue.pop(0)
            self.employee_2_available = False
            paired_time = self.env.now
            self.client_paired_times[client_id] = paired_time
            self.emit_client_paired(client_id, 2, paired_time)
            self.env.process(self.serve_client(client_id, 2))
    
    def serve_client(self, client_id: int, employee_id: int):
        """Serve a client with the specified employee."""
        if employee_id == 1:
            mean = self.employee_1_mean
            stddev = self.employee_1_stddev
        else:
            mean = self.employee_2_mean
            stddev = self.employee_2_stddev
        
        # Sample service duration within allowed range
        min_duration = mean - 3 * stddev
        max_duration = mean + 3 * stddev
        service_duration = clamp_normal(mean, stddev, min_duration, max_duration)
        
        # Wait for service to complete
        yield self.env.timeout(service_duration)
        
        # Check if we're still within simulation time
        if self.env.now > self.simulation_time:
            return
        
        # Emit client_served event
        arrived = self.client_arrival_times[client_id]
        dispatched = self.env.now
        delay = dispatched - arrived
        self.emit_client_served(client_id, employee_id, arrived, dispatched, delay)
        
        # Mark employee as available
        if employee_id == 1:
            self.employee_1_available = True
        else:
            self.employee_2_available = True
        
        # Emit employee_available event
        self.emit_employee_available(employee_id, self.env.now)
        
        # Try to pair next client
        self.try_pair_client()
    
    def client_generator_process(self):
        """Generate clients over time."""
        # First client at t = 0.0
        arrival_time = 0.0
        while arrival_time <= self.simulation_time:
            # Generate client
            client_id = self.next_client_id
            self.next_client_id += 1
            self.client_arrival_times[client_id] = arrival_time
            self.emit_client_generated(client_id, arrival_time)
            
            # Add to queue
            self.waiting_queue.append(client_id)
            
            # Try to pair immediately
            self.try_pair_client()
            
            # Schedule next client
            # Sample inter-arrival time within allowed range
            min_interval = 0.0
            max_interval = self.client_mean + 5 * self.client_stddev
            interval = clamp_normal(self.client_mean, self.client_stddev, 
                                   min_interval, max_interval)
            arrival_time += interval
            
            # Wait until next arrival
            yield self.env.timeout(interval)
    
    def run(self):
        """Run the simulation."""
        # Emit initial employee availability events
        self.emit_employee_available(1, 0.0)
        self.emit_employee_available(2, 0.0)
        
        # Start client generator
        self.env.process(self.client_generator_process())
        
        # Run simulation
        self.env.run(until=self.simulation_time)
        
        # Flush events
        self.logger.flush()


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
        help="Client inter-arrival mean (default: 10.0)"
    )
    parser.add_argument(
        "--client_stddev",
        type=float,
        default=5.0,
        help="Client inter-arrival stddev (default: 5.0)"
    )
    parser.add_argument(
        "--employee_1_mean",
        type=float,
        default=20.0,
        help="Employee 1 service mean (default: 20.0)"
    )
    parser.add_argument(
        "--employee_1_stddev",
        type=float,
        default=0.0,
        help="Employee 1 service stddev (default: 0.0)"
    )
    parser.add_argument(
        "--employee_2_mean",
        type=float,
        default=30.0,
        help="Employee 2 service mean (default: 30.0)"
    )
    parser.add_argument(
        "--employee_2_stddev",
        type=float,
        default=4.0,
        help="Employee 2 service stddev (default: 4.0)"
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
