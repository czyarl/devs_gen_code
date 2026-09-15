#!/usr/bin/env python3
"""
Two-Employee Store Cashier Simulation
"""

import argparse
import json
import random
from datetime import datetime, timedelta
from typing import List, Tuple

# Using SimPy for discrete event simulation
import simpy


class EventLogger:
    """Helper class to log events in the required JSONL format."""
    
    def __init__(self):
        self.events = []
        
    def log_event(self, event_type: str, entity_type: str, entity: str, payload: dict, time: float):
        """Log an event in the required format."""
        # Convert time to HH:MM:SS:mmm format
        hours = int(time // 3600)
        minutes = int((time % 3600) // 60)
        seconds = int(time % 60)
        milliseconds = int((time % 1) * 1000)
        time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"
        
        event = {
            "time": time,
            "time_str": time_str,
            "event": event_type,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload
        }
        self.events.append(event)


class ClientGenerator:
    """Generates clients according to specified inter-arrival time distribution."""
    
    def __init__(self, env: simpy.Environment, logger: EventLogger, 
                 client_mean: float, client_stddev: float):
        self.env = env
        self.logger = logger
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.client_id_counter = 1
        
    def generate_clients(self, queue):
        """Generate clients with inter-arrival times based on normal distribution."""
        # First client arrives at t=0.0
        yield self.env.timeout(0.0)
        self._generate_single_client(queue)
        
        # Generate subsequent clients
        while True:
            # Sample inter-arrival time from normal distribution
            inter_arrival = random.normalvariate(self.client_mean, self.client_stddev)
            
            # Clip to valid range: [0, client_mean + 5 * client_stddev]
            max_interval = self.client_mean + 5 * self.client_stddev
            inter_arrival = max(0.0, min(inter_arrival, max_interval))
            
            yield self.env.timeout(inter_arrival)
            self._generate_single_client(queue)
    
    def _generate_single_client(self, queue):
        """Generate a single client."""
        client_id = self.client_id_counter
        self.client_id_counter += 1
        
        arrival_time = self.env.now
        
        # Log client generation event
        self.logger.log_event(
            event_type="client_generated",
            entity_type="client_generator",
            entity="ClientGenerator",
            payload={"client_id": client_id, "arrival_time": arrival_time},
            time=self.env.now
        )
        
        # Add client to queue
        queue.add_client(client_id, arrival_time)


class Queue:
    """FIFO queue for waiting clients."""
    
    def __init__(self, env: simpy.Environment, logger: EventLogger):
        self.env = env
        self.logger = logger
        self.clients = []  # List of (client_id, arrival_time) tuples
        self.waiting_clients = {}  # client_id -> arrival_time
        
    def add_client(self, client_id: int, arrival_time: float):
        """Add a client to the queue."""
        self.clients.append((client_id, arrival_time))
        self.waiting_clients[client_id] = arrival_time
        
    def get_next_client(self) -> Tuple[int, float]:
        """Get the next client from the queue (FIFO order)."""
        if not self.clients:
            return None, None
            
        client_id, arrival_time = self.clients.pop(0)
        del self.waiting_clients[client_id]
        return client_id, arrival_time
    
    def has_waiting_clients(self) -> bool:
        """Check if there are waiting clients."""
        return len(self.clients) > 0


class Employee:
    """An employee who serves clients."""
    
    def __init__(self, env: simpy.Environment, logger: EventLogger, 
                 employee_id: int, mean_service_time: float, stddev_service_time: float):
        self.env = env
        self.logger = logger
        self.employee_id = employee_id
        self.mean_service_time = mean_service_time
        self.stddev_service_time = stddev_service_time
        self.is_available = True
        self.current_client = None
        self.service_start_time = None
        
    def serve_client(self, client_id: int, arrival_time: float, queue: Queue):
        """Serve a client."""
        # Mark employee as busy
        self.is_available = False
        self.current_client = client_id
        self.service_start_time = self.env.now
        
        # Log employee availability (when employee becomes busy)
        self.logger.log_event(
            event_type="employee_available",
            entity_type="employee",
            entity=f"Employee_{self.employee_id}",
            payload={"employee_id": self.employee_id},
            time=self.env.now
        )
        
        # Calculate service duration
        if self.stddev_service_time == 0:
            # Fixed service time
            service_duration = self.mean_service_time
        else:
            # Sample from normal distribution
            service_duration = random.normalvariate(self.mean_service_time, self.stddev_service_time)
            # Clip to valid range: [mean - 3*stddev, mean + 3*stddev]
            min_duration = self.mean_service_time - 3 * self.stddev_service_time
            max_duration = self.mean_service_time + 3 * self.stddev_service_time
            service_duration = max(min_duration, min(service_duration, max_duration))
        
        # Wait for service to complete
        yield self.env.timeout(service_duration)
        
        # Service completed
        dispatched_time = self.env.now
        delay = dispatched_time - arrival_time
        
        # Log client served event
        self.logger.log_event(
            event_type="client_served",
            entity_type="employee",
            entity=f"Employee_{self.employee_id}",
            payload={
                "client_id": client_id,
                "employee_id": self.employee_id,
                "arrived": arrival_time,
                "dispatched": dispatched_time,
                "delay": delay
            },
            time=self.env.now
        )
        
        # Mark employee as available
        self.is_available = True
        self.current_client = None
        self.service_start_time = None
        
        # Log employee availability (when employee becomes free)
        self.logger.log_event(
            event_type="employee_available",
            entity_type="employee",
            entity=f"Employee_{self.employee_id}",
            payload={"employee_id": self.employee_id},
            time=self.env.now
        )


class CashierSystem:
    """Main cashier system that coordinates clients, queue, and employees."""
    
    def __init__(self, env: simpy.Environment, logger: EventLogger,
                 client_mean: float, client_stddev: float,
                 employee_1_mean: float, employee_1_stddev: float,
                 employee_2_mean: float, employee_2_stddev: float,
                 simulation_time: float):
        self.env = env
        self.logger = logger
        self.simulation_time = simulation_time
        
        # Initialize components
        self.queue = Queue(env, logger)
        self.employee_1 = Employee(env, logger, 1, employee_1_mean, employee_1_stddev)
        self.employee_2 = Employee(env, logger, 2, employee_2_mean, employee_2_stddev)
        self.client_generator = ClientGenerator(env, logger, client_mean, client_stddev)
        
        # Track paired clients
        self.paired_clients = {}  # client_id -> paired_time
        
    def run(self):
        """Run the simulation."""
        # Start client generator
        self.env.process(self.client_generator.generate_clients(self.queue))
        
        # Log initial employee availability
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
        
        # Run simulation until time limit
        while self.env.now < self.simulation_time:
            # Check if there are waiting clients and available employees
            if self.queue.has_waiting_clients():
                # Try to pair with available employee
                if self.employee_1.is_available:
                    client_id, arrival_time = self.queue.get_next_client()
                    if client_id is not None:
                        # Log client pairing
                        paired_time = self.env.now
                        self.logger.log_event(
                            event_type="client_paired",
                            entity_type="queue",
                            entity="Queue",
                            payload={
                                "client_id": client_id,
                                "employee_id": 1,
                                "paired_time": paired_time
                            },
                            time=self.env.now
                        )
                        self.paired_clients[client_id] = paired_time
                        
                        # Start serving the client
                        self.env.process(self.employee_1.serve_client(client_id, arrival_time, self.queue))
                        
                elif self.employee_2.is_available:
                    client_id, arrival_time = self.queue.get_next_client()
                    if client_id is not None:
                        # Log client pairing
                        paired_time = self.env.now
                        self.logger.log_event(
                            event_type="client_paired",
                            entity_type="queue",
                            entity="Queue",
                            payload={
                                "client_id": client_id,
                                "employee_id": 2,
                                "paired_time": paired_time
                            },
                            time=self.env.now
                        )
                        self.paired_clients[client_id] = paired_time
                        
                        # Start serving the client
                        self.env.process(self.employee_2.serve_client(client_id, arrival_time, self.queue))
            
            # Process events until next event or simulation end
            yield self.env.timeout(0.001)  # Small time step to avoid infinite loops


def parse_time_string(time_str: str) -> float:
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
    
    # Set random seed if provided
    if args.seed is not None:
        random.seed(args.seed)
    
    # Parse simulation time
    simulation_time = parse_time_string(args.simulation_time)
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create event logger
    logger = EventLogger()
    
    # Create and run the cashier system
    system = CashierSystem(
        env=env,
        logger=logger,
        client_mean=args.client_mean,
        client_stddev=args.client_stddev,
        employee_1_mean=args.employee_1_mean,
        employee_1_stddev=args.employee_1_stddev,
        employee_2_mean=args.employee_2_mean,
        employee_2_stddev=args.employee_2_stddev,
        simulation_time=simulation_time
    )
    
    # Run simulation
    system.run()
    
    # Sort events by time
    logger.events.sort(key=lambda x: x['time'])
    
    # Print events in JSONL format
    for event in logger.events:
        print(json.dumps(event))


if __name__ == '__main__':
    main()