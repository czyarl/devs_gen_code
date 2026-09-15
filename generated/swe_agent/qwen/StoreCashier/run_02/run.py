#!/usr/bin/env python3
"""
Two-Employee Store Cashier Simulation
"""

import argparse
import json
import random
import sys
from datetime import datetime, timedelta
from typing import List, Tuple
import simpy


class TimeFormatter:
    """Helper class to format time in HH:MM:SS:mmm format"""
    
    @staticmethod
    def format_time(seconds: float) -> str:
        """Format seconds into HH:MM:SS:mmm string"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        seconds_part = int(seconds % 60)
        milliseconds = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds_part:02d}:{milliseconds:03d}"


class Client:
    """Represents a client in the simulation"""
    
    def __init__(self, client_id: int, arrival_time: float):
        self.id = client_id
        self.arrival_time = arrival_time


class Employee:
    """Represents an employee in the simulation"""
    
    def __init__(self, env: simpy.Environment, employee_id: int, mean: float, stddev: float, 
                 emit_event_func):
        self.env = env
        self.id = employee_id
        self.mean = mean
        self.stddev = stddev
        self.is_available = True
        self.current_client = None
        self.service_start_time = None
        self._emit_event = emit_event_func
        
    def serve_client(self, client: Client):
        """Start serving a client"""
        self.current_client = client
        self.service_start_time = self.env.now
        self.is_available = False
        
        # Calculate service duration based on normal distribution
        if self.stddev == 0:
            duration = self.mean
        else:
            # Ensure duration is within bounds
            min_duration = self.mean - 3 * self.stddev
            max_duration = self.mean + 3 * self.stddev
            duration = random.normalvariate(self.mean, self.stddev)
            duration = max(min_duration, min(max_duration, duration))
        
        # Schedule service completion
        yield self.env.timeout(duration)
        
        # Complete service
        self.is_available = True
        self.current_client = None
        self.service_start_time = None
        
        # Emit client served event
        self._emit_event("client_served", {
            "client_id": client.id,
            "employee_id": self.id,
            "arrived": client.arrival_time,
            "dispatched": self.env.now,
            "delay": self.env.now - client.arrival_time
        })
        
        # Emit employee available event
        self._emit_event("employee_available", {"employee_id": self.id})


class ClientGenerator:
    """Generates clients according to specified inter-arrival times"""
    
    def __init__(self, env: simpy.Environment, queue, client_mean: float, client_stddev: float, 
                 emit_event_func):
        self.env = env
        self.queue = queue
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.client_id_counter = 1
        self._emit_event = emit_event_func
        
    def generate_clients(self):
        """Generate clients at specified intervals"""
        # First client at t = 0.0
        # We need to make sure the client is generated first, then paired
        # This is done by yielding a timeout of 0 to ensure proper ordering
        yield self.env.timeout(0)
        client = Client(self.client_id_counter, self.env.now)
        self.client_id_counter += 1
        self.queue.add_client(client)
        self._emit_event("client_generated", {
            "client_id": client.id,
            "arrival_time": client.arrival_time
        })
        
        # Subsequent clients
        while True:
            # Calculate inter-arrival time
            if self.client_stddev == 0:
                interval = self.client_mean
            else:
                # Ensure interval is within bounds
                min_interval = 0
                max_interval = self.client_mean + 5 * self.client_stddev
                interval = random.normalvariate(self.client_mean, self.client_stddev)
                interval = max(min_interval, min(max_interval, interval))
            
            yield self.env.timeout(interval)
            
            # Generate new client
            client = Client(self.client_id_counter, self.env.now)
            self.client_id_counter += 1
            self.queue.add_client(client)
            self._emit_event("client_generated", {
                "client_id": client.id,
                "arrival_time": client.arrival_time
            })


class FIFOQueue:
    """FIFO queue for waiting clients"""
    
    def __init__(self, env: simpy.Environment, employees: List[Employee], emit_event_func):
        self.env = env
        self.employees = employees
        self.clients = []
        self.paired_clients = {}  # client_id -> paired_time
        self._emit_event = emit_event_func
        
    def add_client(self, client: Client):
        """Add a client to the queue"""
        self.clients.append(client)
        # Check for pairing after a small delay to ensure proper event ordering
        self.env.process(self._check_for_pairing_with_delay())
        
    def remove_client(self, client: Client):
        """Remove a client from the queue"""
        if client in self.clients:
            self.clients.remove(client)
            
    def _check_for_pairing_with_delay(self):
        """Check for pairing with a small delay to ensure proper ordering"""
        # This is a workaround to ensure events are emitted in the right order
        yield self.env.timeout(0)
        self._check_for_pairing()
        
    def _check_for_pairing(self):
        """Check if any clients can be paired with available employees"""
        # Find available employees
        available_employees = [emp for emp in self.employees if emp.is_available]
        
        # Pair available clients with available employees
        for client in self.clients[:]:  # Copy list to avoid modification during iteration
            if not available_employees:
                break
                
            # Pair with first available employee
            employee = available_employees.pop(0)
            
            # Remove client from queue
            self.remove_client(client)
            
            # Record pairing
            self.paired_clients[client.id] = self.env.now
            
            # Emit pairing event
            self._emit_event("client_paired", {
                "client_id": client.id,
                "employee_id": employee.id,
                "paired_time": self.env.now
            })
            
            # Start serving
            self.env.process(employee.serve_client(client))


class Simulation:
    """Main simulation class"""
    
    def __init__(self, simulation_time: str, client_mean: float, client_stddev: float,
                 employee_1_mean: float, employee_1_stddev: float,
                 employee_2_mean: float, employee_2_stddev: float, seed: int = None):
        self.simulation_time = self._parse_time(simulation_time)
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.employee_1_mean = employee_1_mean
        self.employee_1_stddev = employee_1_stddev
        self.employee_2_mean = employee_2_mean
        self.employee_2_stddev = employee_2_stddev
        self.seed = seed
        
        # Initialize simulation environment
        self.env = simpy.Environment()
        
        # Create employees
        self.employee_1 = Employee(self.env, 1, employee_1_mean, employee_1_stddev, self._emit_event)
        self.employee_2 = Employee(self.env, 2, employee_2_mean, employee_2_stddev, self._emit_event)
        self.employees = [self.employee_1, self.employee_2]
        
        # Create queue
        self.queue = FIFOQueue(self.env, self.employees, self._emit_event)
        
        # Create client generator
        self.client_generator = ClientGenerator(self.env, self.queue, client_mean, client_stddev, self._emit_event)
        
        # Set random seed if provided
        if seed is not None:
            random.seed(seed)
    
    def _parse_time(self, time_str: str) -> float:
        """Parse time string in HH:MM:SS:mmm format to seconds"""
        hours, minutes, seconds, milliseconds = map(int, time_str.split(':'))
        return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    
    def _emit_event(self, event_type: str, payload: dict):
        """Emit an event to stdout"""
        # Determine entity and entity_type based on event type
        if event_type == "client_generated":
            entity_type = "client_generator"
            entity = "ClientGenerator"
        elif event_type == "client_paired":
            entity_type = "queue"
            entity = "Queue"
        elif event_type == "client_served":
            entity_type = "employee"
            # We need to determine which employee served the client
            entity = "Employee_1" if payload["employee_id"] == 1 else "Employee_2"
        elif event_type == "employee_available":
            entity_type = "employee"
            entity = "Employee_1" if payload["employee_id"] == 1 else "Employee_2"
        else:
            entity_type = "unknown"
            entity = "unknown"
            
        event = {
            "time": self.env.now,
            "time_str": TimeFormatter.format_time(self.env.now),
            "event": event_type,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload
        }
        print(json.dumps(event))
    
    def run(self):
        """Run the simulation"""
        # Start all processes
        self.env.process(self.client_generator.generate_clients())
        
        # Run simulation until time limit
        self.env.run(until=self.simulation_time)
        
        # Emit final employee availability events
        for employee in self.employees:
            if employee.is_available:
                self._emit_event("employee_available", {"employee_id": employee.id})


def main():
    """Main entry point"""
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
    parser.add_argument("--seed", type=int, help="Random seed for reproducibility")
    
    args = parser.parse_args()
    
    # Create and run simulation
    sim = Simulation(
        args.simulation_time,
        args.client_mean,
        args.client_stddev,
        args.employee_1_mean,
        args.employee_1_stddev,
        args.employee_2_mean,
        args.employee_2_stddev,
        args.seed
    )
    
    sim.run()


if __name__ == "__main__":
    main()