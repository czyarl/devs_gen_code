#!/usr/bin/env python3
"""
Two-Employee Store Cashier Simulation
"""

import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
import simpy


class EventLogger:
    """Handles logging of simulation events in JSONL format"""
    
    def __init__(self):
        self.events = []
    
    def log_event(self, event_type: str, entity_type: str, entity: str, payload: dict, time: float):
        """Log an event in JSONL format"""
        # Convert time to HH:MM:SS:mmm format
        time_str = self._format_time(time)
        
        event = {
            "time": time,
            "time_str": time_str,
            "event": event_type,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload
        }
        
        self.events.append(event)
        print(json.dumps(event))
    
    def _format_time(self, time_seconds: float) -> str:
        """Convert seconds to HH:MM:SS:mmm format"""
        hours = int(time_seconds // 3600)
        minutes = int((time_seconds % 3600) // 60)
        seconds = int(time_seconds % 60)
        milliseconds = int((time_seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"


class CashierSystem:
    """Main cashier system that coordinates clients and employees"""
    
    def __init__(self, env: simpy.Environment, logger: EventLogger,
                 client_mean: float, client_stddev: float,
                 employee_1_mean: float, employee_1_stddev: float,
                 employee_2_mean: float, employee_2_stddev: float,
                 simulation_time: float):
        self.env = env
        self.logger = logger
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.employee_1_mean = employee_1_mean
        self.employee_1_stddev = employee_1_stddev
        self.employee_2_mean = employee_2_mean
        self.employee_2_stddev = employee_2_stddev
        self.simulation_time = simulation_time
        
        # Initialize employees
        self.employee_1_available = True
        self.employee_2_available = True
        
        # FIFO queue for waiting clients
        self.queue = []
        
        # Client ID counter
        self.client_id_counter = 1
        
        # Initialize employees as available
        self.logger.log_event(
            event_type="employee_available",
            entity_type="employee",
            entity="Employee_1",
            payload={"employee_id": 1},
            time=0.0
        )
        self.logger.log_event(
            event_type="employee_available",
            entity_type="employee",
            entity="Employee_2",
            payload={"employee_id": 2},
            time=0.0
        )
    
    def generate_clients(self):
        """Generate clients at specified intervals"""
        # First client is generated at t = 0.0
        yield self.env.timeout(0.0)
        self._generate_client()
        
        # Generate subsequent clients
        while True:
            # Sample inter-arrival time
            inter_arrival = random.gauss(self.client_mean, self.client_stddev)
            # Ensure non-negative inter-arrival time
            inter_arrival = max(0, inter_arrival)
            # Apply the constraint: 0 <= interval <= client_mean + 5 * client_stddev
            max_interval = self.client_mean + 5 * self.client_stddev
            inter_arrival = min(inter_arrival, max_interval)
            
            yield self.env.timeout(inter_arrival)
            self._generate_client()
    
    def _generate_client(self):
        """Generate a single client"""
        client_id = self.client_id_counter
        self.client_id_counter += 1
        
        # Log client generation
        self.logger.log_event(
            event_type="client_generated",
            entity_type="client_generator",
            entity="ClientGenerator",
            payload={
                "client_id": client_id,
                "arrival_time": self.env.now
            },
            time=self.env.now
        )
        
        # Add client to queue
        self.queue.append({
            "id": client_id,
            "arrival_time": self.env.now
        })
        
        # Try to pair with available employee
        self._try_pair_client()
    
    def _try_pair_client(self):
        """Try to pair a client with an available employee"""
        # Sort queue by arrival time (FIFO)
        self.queue.sort(key=lambda x: x["arrival_time"])
        
        # If we have clients in queue and at least one employee is available
        if self.queue and (self.employee_1_available or self.employee_2_available):
            client = self.queue[0]
            
            # Try to pair with employee 1 first
            if self.employee_1_available:
                self._pair_client_with_employee(client, 1)
                self.queue.pop(0)
            # Then try employee 2
            elif self.employee_2_available:
                self._pair_client_with_employee(client, 2)
                self.queue.pop(0)
    
    def _pair_client_with_employee(self, client: dict, employee_id: int):
        """Pair a client with an employee"""
        # Log client pairing
        self.logger.log_event(
            event_type="client_paired",
            entity_type="queue",
            entity="Queue",
            payload={
                "client_id": client["id"],
                "employee_id": employee_id,
                "paired_time": self.env.now
            },
            time=self.env.now
        )
        
        # Start serving the client
        self.env.process(self._serve_client(client, employee_id))
    
    def _serve_client(self, client: dict, employee_id: int):
        """Serve a client"""
        # Mark employee as unavailable
        if employee_id == 1:
            self.employee_1_available = False
        else:
            self.employee_2_available = False
        
        # Sample service duration
        if employee_id == 1:
            mean = self.employee_1_mean
            stddev = self.employee_1_stddev
        else:
            mean = self.employee_2_mean
            stddev = self.employee_2_stddev
            
        if stddev == 0:
            # If stddev is 0, service duration equals mean
            duration = mean
        else:
            # Sample from normal distribution
            duration = random.gauss(mean, stddev)
            # Apply constraints: employee_mean - 3 * employee_stddev <= duration <= employee_mean + 3 * employee_stddev
            min_duration = mean - 3 * stddev
            max_duration = mean + 3 * stddev
            duration = max(min_duration, min(duration, max_duration))
        
        # Wait for service to complete
        yield self.env.timeout(duration)
        
        # Log client served
        self.logger.log_event(
            event_type="client_served",
            entity_type="employee",
            entity=f"Employee_{employee_id}",
            payload={
                "client_id": client["id"],
                "employee_id": employee_id,
                "arrived": client["arrival_time"],
                "dispatched": self.env.now,
                "delay": self.env.now - client["arrival_time"]
            },
            time=self.env.now
        )
        
        # Mark employee as available
        if employee_id == 1:
            self.employee_1_available = True
        else:
            self.employee_2_available = True
        
        # Log employee availability
        self.logger.log_event(
            event_type="employee_available",
            entity_type="employee",
            entity=f"Employee_{employee_id}",
            payload={"employee_id": employee_id},
            time=self.env.now
        )
        
        # Try to pair next client
        self._try_pair_client()


def parse_time_string(time_str: str) -> float:
    """Parse HH:MM:SS:mmm format to seconds"""
    try:
        hours, minutes, seconds, milliseconds = map(int, time_str.split(':'))
        return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    except ValueError:
        raise ValueError(f"Invalid time format: {time_str}. Expected HH:MM:SS:mmm")


def main():
    """Main function to run the simulation"""
    parser = argparse.ArgumentParser(description="Two-Employee Store Cashier Simulation")
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000",
                       help="Total simulation horizon in HH:MM:SS:mmm format. Default: 00:05:00:000")
    parser.add_argument("--client_mean", type=float, default=10.0,
                       help="Client inter-arrival mean. Default: 10.0")
    parser.add_argument("--client_stddev", type=float, default=5.0,
                       help="Client inter-arrival standard deviation. Default: 5.0")
    parser.add_argument("--employee_1_mean", type=float, default=20.0,
                       help="Employee 1 service mean. Default: 20.0")
    parser.add_argument("--employee_1_stddev", type=float, default=0.0,
                       help="Employee 1 service standard deviation. Default: 0.0")
    parser.add_argument("--employee_2_mean", type=float, default=30.0,
                       help="Employee 2 service mean. Default: 30.0")
    parser.add_argument("--employee_2_stddev", type=float, default=4.0,
                       help="Employee 2 service standard deviation. Default: 4.0")
    parser.add_argument("--seed", type=int, help="Random seed for reproducibility")
    
    args = parser.parse_args()
    
    # Set random seed if provided
    if args.seed is not None:
        random.seed(args.seed)
    
    # Parse simulation time
    simulation_time = parse_time_string(args.simulation_time)
    
    # Create simulation environment
    env = simpy.Environment()
    logger = EventLogger()
    
    # Create and run the cashier system
    system = CashierSystem(
        env, logger,
        args.client_mean, args.client_stddev,
        args.employee_1_mean, args.employee_1_stddev,
        args.employee_2_mean, args.employee_2_stddev,
        simulation_time
    )
    
    # Start client generation
    env.process(system.generate_clients())
    
    # Run the simulation
    env.run(until=simulation_time)


if __name__ == "__main__":
    main()