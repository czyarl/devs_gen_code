#!/usr/bin/env python3
"""
Two-Employee Store Cashier Simulation
"""

import argparse
import json
import random
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
import simpy


class EventLogger:
    """Handles logging of simulation events in JSONL format."""
    
    def __init__(self, env: simpy.Environment):
        self.env = env
        self.events = []
        
    def format_time(self, time_value: float) -> str:
        """Convert simulation time to HH:MM:SS:mmm format."""
        hours = int(time_value // 3600)
        minutes = int((time_value % 3600) // 60)
        seconds = int(time_value % 60)
        milliseconds = int((time_value % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"
    
    def log_event(self, event_type: str, entity_type: str, entity: str, payload: Dict):
        """Log a simulation event."""
        event = {
            "time": self.env.now,
            "time_str": self.format_time(self.env.now),
            "event": event_type,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload
        }
        print(json.dumps(event))


class ClientGenerator:
    """Generates clients according to specified inter-arrival time distribution."""
    
    def __init__(self, env: simpy.Environment, logger: EventLogger, 
                 queue_manager, client_mean: float, client_stddev: float):
        self.env = env
        self.logger = logger
        self.queue_manager = queue_manager
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.client_id_counter = 1
        
    def generate_clients(self):
        """Generate clients with inter-arrival times based on normal distribution."""
        # First client arrives at t=0.0
        yield self.env.timeout(0.0)
        self.generate_client()
        
        # Generate subsequent clients
        while True:
            # Sample inter-arrival time from normal distribution
            inter_arrival = random.normalvariate(self.client_mean, self.client_stddev)
            
            # Clamp to valid range: [0, client_mean + 5 * client_stddev]
            max_interval = self.client_mean + 5 * self.client_stddev
            inter_arrival = max(0.0, min(inter_arrival, max_interval))
            
            yield self.env.timeout(inter_arrival)
            self.generate_client()
    
    def generate_client(self):
        """Generate a single client."""
        client_id = self.client_id_counter
        self.client_id_counter += 1
        
        self.logger.log_event(
            "client_generated",
            "client_generator",
            "ClientGenerator",
            {
                "client_id": client_id,
                "arrival_time": self.env.now
            }
        )
        
        # Add client to queue
        self.queue_manager.add_client(client_id, self.env.now)


class QueueManager:
    """Manages the FIFO queue of waiting clients."""
    
    def __init__(self, env: simpy.Environment, logger: EventLogger):
        self.env = env
        self.logger = logger
        self.waiting_clients = []  # List of (client_id, arrival_time) tuples
    
    def add_client(self, client_id: int, arrival_time: float):
        """Add a client to the queue."""
        self.waiting_clients.append((client_id, arrival_time))
        
    def get_next_client(self) -> Tuple[int, float]:
        """Get the next client from the queue (FIFO)."""
        if not self.waiting_clients:
            return None, None
        return self.waiting_clients.pop(0)
    
    def has_waiting_clients(self) -> bool:
        """Check if there are waiting clients."""
        return len(self.waiting_clients) > 0


class Employee:
    """Represents an employee who serves clients."""
    
    def __init__(self, env: simpy.Environment, logger: EventLogger, 
                 employee_id: int, mean_service_time: float, stddev_service_time: float):
        self.env = env
        self.logger = logger
        self.employee_id = employee_id
        self.mean_service_time = mean_service_time
        self.stddev_service_time = stddev_service_time
        self.is_available = True
        self.current_client_id = None
        self.current_client_arrival = None
        self.paired_time = None
        
    def serve_client(self, client_id: int, arrival_time: float):
        """Serve a client."""
        self.current_client_id = client_id
        self.current_client_arrival = arrival_time
        self.paired_time = self.env.now
        
        # Sample service duration from normal distribution
        if self.stddev_service_time == 0:
            service_duration = self.mean_service_time
        else:
            service_duration = random.normalvariate(self.mean_service_time, self.stddev_service_time)
            # Clamp to valid range: [mean - 3*stddev, mean + 3*stddev]
            min_duration = self.mean_service_time - 3 * self.stddev_service_time
            max_duration = self.mean_service_time + 3 * self.stddev_service_time
            service_duration = max(min_duration, min(service_duration, max_duration))
        
        # Log client pairing
        self.logger.log_event(
            "client_paired",
            "queue",
            "Queue",
            {
                "client_id": client_id,
                "employee_id": self.employee_id,
                "paired_time": self.env.now
            }
        )
        
        # Wait for service to complete
        yield self.env.timeout(service_duration)
        
        # Log client served
        dispatched_time = self.env.now
        delay = dispatched_time - arrival_time
        
        self.logger.log_event(
            "client_served",
            "employee",
            f"Employee_{self.employee_id}",
            {
                "client_id": client_id,
                "employee_id": self.employee_id,
                "arrived": arrival_time,
                "dispatched": dispatched_time,
                "delay": delay
            }
        )
        
        # Mark employee as available
        self.is_available = True
        self.current_client_id = None
        self.current_client_arrival = None
        self.paired_time = None
        
        # Log employee availability
        self.logger.log_event(
            "employee_available",
            "employee",
            f"Employee_{self.employee_id}",
            {
                "employee_id": self.employee_id
            }
        )


def run_simulation(simulation_time: str, 
                   client_mean: float, client_stddev: float,
                   employee_1_mean: float, employee_1_stddev: float,
                   employee_2_mean: float, employee_2_stddev: float,
                   seed: int = None):
    """Run the simulation with given parameters."""
    
    if seed is not None:
        random.seed(seed)
    
    # Parse simulation time
    time_parts = simulation_time.split(':')
    hours, minutes, seconds, milliseconds = map(int, time_parts)
    total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    
    # Create environment
    env = simpy.Environment()
    logger = EventLogger(env)
    
    # Create components
    queue_manager = QueueManager(env, logger)
    client_generator = ClientGenerator(env, logger, queue_manager, client_mean, client_stddev)
    employee_1 = Employee(env, logger, 1, employee_1_mean, employee_1_stddev)
    employee_2 = Employee(env, logger, 2, employee_2_mean, employee_2_stddev)
    
    # Start client generation
    env.process(client_generator.generate_clients())
    
    # Initialize employees as available
    logger.log_event(
        "employee_available",
        "employee",
        "Employee_1",
        {"employee_id": 1}
    )
    logger.log_event(
        "employee_available",
        "employee",
        "Employee_2",
        {"employee_id": 2}
    )
    
    # Main simulation logic using SimPy's event system
    def simulation_logic():
        # This function handles the core logic of pairing clients with employees
        while True:
            # Check if there are waiting clients and available employees
            if queue_manager.has_waiting_clients():
                # Check if either employee is available
                if employee_1.is_available:
                    client_id, arrival_time = queue_manager.get_next_client()
                    if client_id is not None:
                        employee_1.is_available = False
                        env.process(employee_1.serve_client(client_id, arrival_time))
                        
                elif employee_2.is_available:
                    client_id, arrival_time = queue_manager.get_next_client()
                    if client_id is not None:
                        employee_2.is_available = False
                        env.process(employee_2.serve_client(client_id, arrival_time))
            
            # Wait for a small amount of time before checking again
            # This prevents busy waiting but still allows timely processing
            yield env.timeout(0.001)
    
    # Run the simulation
    env.process(simulation_logic())
    env.run(until=total_seconds)


def main():
    """Main function to parse arguments and run simulation."""
    parser = argparse.ArgumentParser(description="Two-Employee Store Cashier Simulation")
    
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000",
                       help="Total simulation horizon in HH:MM:SS:mmm format")
    parser.add_argument("--client_mean", type=float, default=10.0,
                       help="Client inter-arrival mean")
    parser.add_argument("--client_stddev", type=float, default=5.0,
                       help="Client inter-arrival standard deviation")
    parser.add_argument("--employee_1_mean", type=float, default=20.0,
                       help="Employee 1 service mean")
    parser.add_argument("--employee_1_stddev", type=float, default=0.0,
                       help="Employee 1 service standard deviation")
    parser.add_argument("--employee_2_mean", type=float, default=30.0,
                       help="Employee 2 service mean")
    parser.add_argument("--employee_2_stddev", type=float, default=4.0,
                       help="Employee 2 service standard deviation")
    parser.add_argument("--seed", type=int, default=None,
                       help="Random seed for reproducibility")
    
    args = parser.parse_args()
    
    run_simulation(
        args.simulation_time,
        args.client_mean,
        args.client_stddev,
        args.employee_1_mean,
        args.employee_1_stddev,
        args.employee_2_mean,
        args.employee_2_stddev,
        args.seed
    )


if __name__ == "__main__":
    main()