#!/usr/bin/env python3
"""
Two-Employee Store Cashier Simulation
"""

import argparse
import json
import math
import random
from datetime import datetime, timedelta
import simpy


class EventLogger:
    """Handles logging of events in the required JSONL format."""
    
    def __init__(self):
        self.events = []
        
    def format_time(self, time_value):
        """Convert simulation time to HH:MM:SS:mmm format."""
        hours = int(time_value // 3600)
        minutes = int((time_value % 3600) // 60)
        seconds = int(time_value % 60)
        milliseconds = int((time_value % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"
    
    def emit_event(self, event_type, entity_type, entity, payload, time_value):
        """Emit an event in the required JSONL format."""
        event = {
            "time": time_value,
            "time_str": self.format_time(time_value),
            "event": event_type,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload
        }
        print(json.dumps(event))
        

class ClientGenerator:
    """Generates clients according to specified arrival distribution."""
    
    def __init__(self, env, logger, client_mean, client_stddev, queue):
        self.env = env
        self.logger = logger
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.queue = queue
        self.client_id = 0
        
    def generate_clients(self):
        """Generate clients at specified intervals."""
        # Generate first client at t=0.0
        yield self.env.timeout(0.0)
        self._generate_client()
        
        # Generate subsequent clients
        while True:
            # Sample inter-arrival time from normal distribution
            interval = random.normalvariate(self.client_mean, self.client_stddev)
            
            # Clip to valid range: [0, client_mean + 5 * client_stddev]
            max_interval = self.client_mean + 5 * self.client_stddev
            interval = max(0.0, min(interval, max_interval))
            
            yield self.env.timeout(interval)
            self._generate_client()
    
    def _generate_client(self):
        """Generate a single client."""
        self.client_id += 1
        arrival_time = self.env.now
        
        self.logger.emit_event(
            "client_generated",
            "client_generator",
            "ClientGenerator",
            {"client_id": self.client_id, "arrival_time": arrival_time},
            self.env.now
        )
        
        # Add client to queue
        self.queue.add_client(self.client_id, arrival_time)


class QueueManager:
    """Manages the FIFO queue of waiting clients."""
    
    def __init__(self, env, logger, employees):
        self.env = env
        self.logger = logger
        self.employees = employees
        self.clients = []  # List of (client_id, arrival_time) tuples
        self.waiting_clients = {}  # client_id -> arrival_time
        
    def add_client(self, client_id, arrival_time):
        """Add a client to the queue."""
        self.clients.append((client_id, arrival_time))
        self.waiting_clients[client_id] = arrival_time
        self._try_pair_client()
        
    def remove_client(self, client_id):
        """Remove a client from the queue."""
        if client_id in self.waiting_clients:
            del self.waiting_clients[client_id]
            
    def _try_pair_client(self):
        """Try to pair waiting clients with available employees."""
        # Check if there are waiting clients and available employees
        if not self.clients or len(self.employees.available_employees) == 0:
            return
            
        # Find the earliest waiting client
        earliest_client = min(self.clients, key=lambda x: x[1])
        client_id, arrival_time = earliest_client
        
        # Get an available employee
        if self.employees.available_employees:
            employee_id = self.employees.available_employees.pop(0)
            self._pair_client_with_employee(client_id, employee_id, arrival_time)
            
    def _pair_client_with_employee(self, client_id, employee_id, arrival_time):
        """Pair a client with an employee."""
        paired_time = self.env.now
        
        self.logger.emit_event(
            "client_paired",
            "queue",
            "Queue",
            {"client_id": client_id, "employee_id": employee_id, "paired_time": paired_time},
            self.env.now
        )
        
        # Start serving the client
        self.employees.start_service(employee_id, client_id, arrival_time, paired_time)


class EmployeeManager:
    """Manages employee availability and service."""
    
    def __init__(self, env, logger, employee_1_mean, employee_1_stddev, employee_2_mean, employee_2_stddev):
        self.env = env
        self.logger = logger
        self.employee_1_mean = employee_1_mean
        self.employee_1_stddev = employee_1_stddev
        self.employee_2_mean = employee_2_mean
        self.employee_2_stddev = employee_2_stddev
        self.available_employees = [1, 2]  # Initially both employees are available
        self.current_clients = {1: None, 2: None}  # employee_id -> client_id
        
        # Emit initial availability events
        self.logger.emit_event(
            "employee_available",
            "employee",
            "Employee_1",
            {"employee_id": 1},
            self.env.now
        )
        self.logger.emit_event(
            "employee_available",
            "employee",
            "Employee_2",
            {"employee_id": 2},
            self.env.now
        )
        
    def start_service(self, employee_id, client_id, arrival_time, paired_time):
        """Start service for a client with an employee."""
        self.current_clients[employee_id] = (client_id, arrival_time, paired_time)
        
        # Sample service duration
        if employee_id == 1:
            mean = self.employee_1_mean
            stddev = self.employee_1_stddev
        else:
            mean = self.employee_2_mean
            stddev = self.employee_2_stddev
            
        # Sample service duration from normal distribution
        if stddev == 0:
            duration = mean
        else:
            duration = random.normalvariate(mean, stddev)
            # Clip to valid range: [mean - 3 * stddev, mean + 3 * stddev]
            min_duration = mean - 3 * stddev
            max_duration = mean + 3 * stddev
            duration = max(min_duration, min(duration, max_duration))
            
        # Schedule service completion
        yield self.env.timeout(duration)
        self.complete_service(employee_id, client_id, arrival_time)
        
    def complete_service(self, employee_id, client_id, arrival_time):
        """Complete service for a client."""
        dispatched_time = self.env.now
        delay = dispatched_time - arrival_time
        
        self.logger.emit_event(
            "client_served",
            "employee",
            f"Employee_{employee_id}",
            {
                "client_id": client_id,
                "employee_id": employee_id,
                "arrived": arrival_time,
                "dispatched": dispatched_time,
                "delay": delay
            },
            self.env.now
        )
        
        # Mark employee as available
        self.available_employees.append(employee_id)
        self.current_clients[employee_id] = None
        
        self.logger.emit_event(
            "employee_available",
            "employee",
            f"Employee_{employee_id}",
            {"employee_id": employee_id},
            self.env.now
        )


def run_simulation(simulation_time, client_mean, client_stddev, 
                   employee_1_mean, employee_1_stddev, 
                   employee_2_mean, employee_2_stddev, seed=None):
    """Run the simulation with given parameters."""
    
    if seed is not None:
        random.seed(seed)
        
    # Create environment
    env = simpy.Environment()
    logger = EventLogger()
    
    # Create queue manager
    queue = QueueManager(env, logger, EmployeeManager(env, logger, employee_1_mean, employee_1_stddev, employee_2_mean, employee_2_stddev))
    
    # Create client generator
    client_gen = ClientGenerator(env, logger, client_mean, client_stddev, queue)
    env.process(client_gen.generate_clients())
    
    # Run simulation
    env.run(until=simulation_time)


def parse_time_string(time_str):
    """Parse time string in HH:MM:SS:mmm format to seconds."""
    h, m, s, ms = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s + ms / 1000.0


def main():
    parser = argparse.ArgumentParser(description='Two-Employee Store Cashier Simulation')
    parser.add_argument('--simulation_time', type=str, default='00:05:00:000',
                        help='Total simulation horizon in HH:MM:SS:mmm format. Default "00:05:00:000".')
    parser.add_argument('--client_mean', type=float, default=10.0,
                        help='Client inter-arrival mean. Default 10.0.')
    parser.add_argument('--client_stddev', type=float, default=5.0,
                        help='Client inter-arrival standard deviation. Default 5.0.')
    parser.add_argument('--employee_1_mean', type=float, default=20.0,
                        help='Employee 1 service mean. Default 20.0.')
    parser.add_argument('--employee_1_stddev', type=float, default=0.0,
                        help='Employee 1 service standard deviation. Default 0.0.')
    parser.add_argument('--employee_2_mean', type=float, default=30.0,
                        help='Employee 2 service mean. Default 30.0.')
    parser.add_argument('--employee_2_stddev', type=float, default=4.0,
                        help='Employee 2 service standard deviation. Default 4.0.')
    parser.add_argument('--seed', type=int, default=None,
                        help='Random seed for reproducibility.')
    
    args = parser.parse_args()
    
    # Parse simulation time
    simulation_time = parse_time_string(args.simulation_time)
    
    # Run simulation
    run_simulation(
        simulation_time=simulation_time,
        client_mean=args.client_mean,
        client_stddev=args.client_stddev,
        employee_1_mean=args.employee_1_mean,
        employee_1_stddev=args.employee_1_stddev,
        employee_2_mean=args.employee_2_mean,
        employee_2_stddev=args.employee_2_stddev,
        seed=args.seed
    )


if __name__ == '__main__':
    main()