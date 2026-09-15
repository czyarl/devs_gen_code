#!/usr/bin/env python3
"""
Two-Employee Store Cashier Simulation
"""

import argparse
import json
import random
from typing import Dict, Tuple
import simpy


class TimeFormatter:
    """Helper class to format time in HH:MM:SS:mmm format"""
    
    @staticmethod
    def format_time(seconds: float) -> str:
        """Convert seconds to HH:MM:SS:mmm format"""
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millisecs = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}:{millisecs:03d}"


class EventLogger:
    """Handles logging of events in JSONL format"""
    
    @staticmethod
    def log_event(event_type: str, entity_type: str, entity: str, payload: Dict, time: float):
        """Log a single event in JSONL format"""
        event = {
            "time": time,
            "time_str": TimeFormatter.format_time(time),
            "event": event_type,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload
        }
        print(json.dumps(event))


class ClientGenerator:
    """Generates clients according to specified inter-arrival time distribution"""
    
    def __init__(self, env: simpy.Environment, client_mean: float, client_stddev: float):
        self.env = env
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.client_id_counter = 1
        
    def generate_clients(self, queue):
        """Generate clients with inter-arrival times based on normal distribution"""
        # Generate first client immediately
        self._generate_client(queue)
        
        # Generate subsequent clients
        while True:
            # Sample inter-arrival time from normal distribution
            inter_arrival = random.normalvariate(self.client_mean, self.client_stddev)
            
            # Clip to valid range: [0, client_mean + 5 * client_stddev]
            max_interval = self.client_mean + 5 * self.client_stddev
            inter_arrival = max(0, min(inter_arrival, max_interval))
            
            yield self.env.timeout(inter_arrival)
            self._generate_client(queue)
    
    def _generate_client(self, queue):
        """Generate a single client"""
        client_id = self.client_id_counter
        self.client_id_counter += 1
        
        # Record client generation
        EventLogger.log_event(
            "client_generated",
            "client_generator",
            "ClientGenerator",
            {"client_id": client_id, "arrival_time": self.env.now},
            self.env.now
        )
        
        # Add client to queue
        queue.add_client(client_id, self.env.now)


class Queue:
    """FIFO queue for waiting clients"""
    
    def __init__(self, env: simpy.Environment):
        self.env = env
        self.clients = []  # List of (client_id, arrival_time) tuples
        self.waiting_clients = {}  # client_id -> arrival_time
    
    def add_client(self, client_id: int, arrival_time: float):
        """Add a client to the queue"""
        self.clients.append((client_id, arrival_time))
        self.waiting_clients[client_id] = arrival_time
    
    def get_next_client(self) -> Tuple[int, float]:
        """Get the next client from the queue (FIFO)"""
        if not self.clients:
            return None, None
            
        client_id, arrival_time = self.clients.pop(0)
        del self.waiting_clients[client_id]
        return client_id, arrival_time
    
    def has_clients(self) -> bool:
        """Check if there are clients in the queue"""
        return len(self.clients) > 0


class Employee:
    """Employee who serves clients"""
    
    def __init__(self, env: simpy.Environment, employee_id: int, mean_service_time: float, stddev_service_time: float):
        self.env = env
        self.employee_id = employee_id
        self.mean_service_time = mean_service_time
        self.stddev_service_time = stddev_service_time
        self.is_available = True
        self.current_client = None
        self.current_paired_time = None
        self.current_arrival_time = None
    
    def serve_client(self, client_id: int, arrival_time: float, queue: Queue):
        """Serve a client"""
        self.current_client = client_id
        self.current_arrival_time = arrival_time
        self.current_paired_time = self.env.now
        
        # Sample service duration from normal distribution
        if self.stddev_service_time == 0:
            # Fixed service time
            service_duration = self.mean_service_time
        else:
            # Sample from normal distribution
            service_duration = random.normalvariate(self.mean_service_time, self.stddev_service_time)
            
            # Clip to valid range: [mean - 3 * stddev, mean + 3 * stddev]
            min_duration = self.mean_service_time - 3 * self.stddev_service_time
            max_duration = self.mean_service_time + 3 * self.stddev_service_time
            service_duration = max(min_duration, min(service_duration, max_duration))
        
        # Wait for service to complete
        yield self.env.timeout(service_duration)
        
        # Record client served
        delay = self.env.now - arrival_time
        EventLogger.log_event(
            "client_served",
            "employee",
            f"Employee_{self.employee_id}",
            {
                "client_id": client_id,
                "employee_id": self.employee_id,
                "arrived": arrival_time,
                "dispatched": self.env.now,
                "delay": delay
            },
            self.env.now
        )
        
        # Mark employee as available
        self.is_available = True
        self.current_client = None
        self.current_arrival_time = None
        self.current_paired_time = None
        
        # Log employee availability
        EventLogger.log_event(
            "employee_available",
            "employee",
            f"Employee_{self.employee_id}",
            {"employee_id": self.employee_id},
            self.env.now
        )


def run_simulation(simulation_time: str, client_mean: float, client_stddev: float,
                   employee_1_mean: float, employee_1_stddev: float,
                   employee_2_mean: float, employee_2_stddev: float):
    """Run the simulation with given parameters"""
    
    # Parse simulation time
    time_parts = simulation_time.split(':')
    hours, minutes, seconds, milliseconds = map(int, time_parts)
    total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    
    # Set up simulation environment
    env = simpy.Environment()
    
    # Create components
    queue = Queue(env)
    employee_1 = Employee(env, 1, employee_1_mean, employee_1_stddev)
    employee_2 = Employee(env, 2, employee_2_mean, employee_2_stddev)
    client_generator = ClientGenerator(env, client_mean, client_stddev)
    
    # Log initial employee availability
    EventLogger.log_event(
        "employee_available",
        "employee",
        "Employee_1",
        {"employee_id": 1},
        0.0
    )
    EventLogger.log_event(
        "employee_available",
        "employee",
        "Employee_2",
        {"employee_id": 2},
        0.0
    )
    
    # Start processes
    env.process(client_generator.generate_clients(queue))
    
    # Simple approach: We'll just run the simulation and let the processes handle events naturally
    # The pairing will happen automatically as events occur in the simulation
    def pairing_logic():
        """Simple pairing logic that runs continuously"""
        while True:
            # Check if we have clients and available employees
            if queue.has_clients() and (employee_1.is_available or employee_2.is_available):
                # Get next client from queue
                client_id, arrival_time = queue.get_next_client()
                
                # Assign to available employee (prefer employee 1)
                if employee_1.is_available:
                    employee = employee_1
                elif employee_2.is_available:
                    employee = employee_2
                else:
                    # This shouldn't happen, but just in case
                    yield env.timeout(0.001)
                    continue
                
                # Mark employee as busy
                employee.is_available = False
                
                # Log client pairing
                EventLogger.log_event(
                    "client_paired",
                    "queue",
                    "Queue",
                    {
                        "client_id": client_id,
                        "employee_id": employee.employee_id,
                        "paired_time": env.now
                    },
                    env.now
                )
                
                # Start serving the client
                env.process(employee.serve_client(client_id, arrival_time, queue))
            
            # Small delay to avoid busy waiting
            yield env.timeout(0.001)
    
    # Start pairing process
    env.process(pairing_logic())
    
    # Run simulation until time limit
    env.run(until=total_seconds)


def main():
    parser = argparse.ArgumentParser(description="Two-Employee Store Cashier Simulation")
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000",
                       help="Total simulation horizon in HH:MM:SS:mmm format (default: 00:05:00:000)")
    parser.add_argument("--client_mean", type=float, default=10.0,
                       help="Client inter-arrival mean (default: 10.0)")
    parser.add_argument("--client_stddev", type=float, default=5.0,
                       help="Client inter-arrival standard deviation (default: 5.0)")
    parser.add_argument("--employee_1_mean", type=float, default=20.0,
                       help="Employee 1 service mean (default: 20.0)")
    parser.add_argument("--employee_1_stddev", type=float, default=0.0,
                       help="Employee 1 service standard deviation (default: 0.0)")
    parser.add_argument("--employee_2_mean", type=float, default=30.0,
                       help="Employee 2 service mean (default: 30.0)")
    parser.add_argument("--employee_2_stddev", type=float, default=4.0,
                       help="Employee 2 service standard deviation (default: 4.0)")
    parser.add_argument("--seed", type=int, help="Random seed for reproducibility")
    
    args = parser.parse_args()
    
    # Set random seed if provided
    if args.seed is not None:
        random.seed(args.seed)
    
    # Run simulation
    run_simulation(
        args.simulation_time,
        args.client_mean,
        args.client_stddev,
        args.employee_1_mean,
        args.employee_1_stddev,
        args.employee_2_mean,
        args.employee_2_stddev
    )


if __name__ == "__main__":
    main()