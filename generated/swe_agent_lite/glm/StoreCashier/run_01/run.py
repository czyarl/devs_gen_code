#!/usr/bin/env python3
"""
Two-Employee Store Cashier Simulation
Discrete Event Simulation using simpy
"""

import argparse
import json
import random
import simpy
from datetime import datetime, timedelta


def parse_time_str(time_str):
    """Parse HH:MM:SS:mmm format to seconds"""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    millis = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + millis / 1000.0


def format_time_str(seconds):
    """Format seconds to HH:MM:SS:mmm format"""
    td = timedelta(seconds=seconds)
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    millis = int((seconds - total_seconds) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{millis:03d}"


def truncated_normal(mean, stddev, min_val, max_val):
    """Sample from truncated normal distribution"""
    while True:
        value = random.gauss(mean, stddev)
        if min_val <= value <= max_val:
            return value


class EventLogger:
    """Logger for simulation events in JSONL format"""
    
    def __init__(self):
        self.events = []
    
    def log(self, time, event_type, entity_type, entity, payload):
        """Log an event"""
        event = {
            "time": round(time, 6),
            "time_str": format_time_str(time),
            "event": event_type,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload
        }
        self.events.append(event)
    
    def print_events(self):
        """Print all events in JSONL format"""
        for event in self.events:
            print(json.dumps(event))


class ClientGenerator:
    """Generates clients at random intervals"""
    
    def __init__(self, env, logger, queue, client_mean, client_stddev, simulation_time):
        self.env = env
        self.logger = logger
        self.queue = queue
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.simulation_time = simulation_time
        self.client_id = 0
        self.action = env.process(self.generate())
    
    def generate(self):
        """Generate clients over time"""
        while True:
            # Check if we're still within simulation time
            if self.env.now >= self.simulation_time:
                break
            
            # Generate new client
            self.client_id += 1
            arrival_time = self.env.now
            
            # Log client_generated event
            self.logger.log(
                time=arrival_time,
                event_type="client_generated",
                entity_type="client_generator",
                entity="ClientGenerator",
                payload={"client_id": self.client_id, "arrival_time": round(arrival_time, 6)}
            )
            
            # Add client to queue
            self.queue.add_client(self.client_id, arrival_time)
            
            # Schedule next client generation
            # Inter-arrival time: 0 <= interval <= client_mean + 5 * client_stddev
            max_interval = self.client_mean + 5 * self.client_stddev
            interval = truncated_normal(self.client_mean, self.client_stddev, 0, max_interval)
            
            # Check if next generation would exceed simulation time
            if self.env.now + interval > self.simulation_time:
                break
            
            yield self.env.timeout(interval)


class Queue:
    """FIFO queue for waiting clients"""
    
    def __init__(self, env, logger, employees):
        self.env = env
        self.logger = logger
        self.employees = employees
        self.waiting_clients = []  # List of (client_id, arrival_time) tuples
        self.paired_clients = {}  # client_id -> paired_time
    
    def add_client(self, client_id, arrival_time):
        """Add a client to the queue"""
        self.waiting_clients.append((client_id, arrival_time))
        self.try_pair()
    
    def try_pair(self):
        """Try to pair waiting clients with available employees"""
        while self.waiting_clients:
            # Find an available employee
            available_employee = None
            for emp in self.employees:
                if emp.is_available():
                    available_employee = emp
                    break
            
            if available_employee is None:
                break
            
            # Get next client in FIFO order
            client_id, arrival_time = self.waiting_clients.pop(0)
            
            # Pair client with employee
            paired_time = self.env.now
            self.paired_clients[client_id] = paired_time
            
            # Log client_paired event
            self.logger.log(
                time=paired_time,
                event_type="client_paired",
                entity_type="queue",
                entity="Queue",
                payload={
                    "client_id": client_id,
                    "employee_id": available_employee.employee_id,
                    "paired_time": round(paired_time, 6)
                }
            )
            
            # Assign client to employee
            available_employee.serve_client(client_id, arrival_time)


class Employee:
    """Employee that serves clients"""
    
    def __init__(self, env, logger, employee_id, mean, stddev, simulation_time):
        self.env = env
        self.logger = logger
        self.employee_id = employee_id
        self.mean = mean
        self.stddev = stddev
        self.simulation_time = simulation_time
        self.current_client = None
        self.current_client_arrival = None
        self.busy = False
        self.resource = simpy.Resource(env, capacity=1)
        
        # Log initial availability at t=0.0
        self.logger.log(
            time=0.0,
            event_type="employee_available",
            entity_type="employee",
            entity=f"Employee_{employee_id}",
            payload={"employee_id": employee_id}
        )
    
    def is_available(self):
        """Check if employee is available"""
        return not self.busy
    
    def serve_client(self, client_id, arrival_time):
        """Start serving a client"""
        self.current_client = client_id
        self.current_client_arrival = arrival_time
        self.busy = True
        
        # Calculate service duration
        # employee_mean - 3 * employee_stddev <= duration <= employee_mean + 3 * employee_stddev
        if self.stddev == 0:
            duration = self.mean
        else:
            min_duration = self.mean - 3 * self.stddev
            max_duration = self.mean + 3 * self.stddev
            duration = truncated_normal(self.mean, self.stddev, min_duration, max_duration)
        
        # Check if service would exceed simulation time
        if self.env.now + duration > self.simulation_time:
            # Don't serve if it would exceed simulation time
            self.busy = False
            self.current_client = None
            self.current_client_arrival = None
            return
        
        # Schedule service completion
        self.env.process(self.complete_service(duration))
    
    def complete_service(self, duration):
        """Complete service after duration"""
        yield self.env.timeout(duration)
        
        # Check if we're still within simulation time
        if self.env.now > self.simulation_time:
            return
        
        # Log client_served event
        dispatched = self.env.now
        arrived = self.current_client_arrival
        delay = dispatched - arrived
        
        self.logger.log(
            time=dispatched,
            event_type="client_served",
            entity_type="employee",
            entity=f"Employee_{self.employee_id}",
            payload={
                "client_id": self.current_client,
                "employee_id": self.employee_id,
                "arrived": round(arrived, 6),
                "dispatched": round(dispatched, 6),
                "delay": round(delay, 6)
            }
        )
        
        # Mark employee as available
        self.busy = False
        client_id = self.current_client
        self.current_client = None
        self.current_client_arrival = None
        
        # Log employee_available event
        self.logger.log(
            time=dispatched,
            event_type="employee_available",
            entity_type="employee",
            entity=f"Employee_{self.employee_id}",
            payload={"employee_id": self.employee_id}
        )


def run_simulation(args):
    """Run the simulation"""
    # Parse simulation time
    simulation_time = parse_time_str(args.simulation_time)
    
    # Set random seed if provided
    if args.seed is not None:
        random.seed(args.seed)
    
    # Create SimPy environment
    env = simpy.Environment()
    
    # Create event logger
    logger = EventLogger()
    
    # Create employees
    employee1 = Employee(
        env, logger, 1,
        args.employee_1_mean, args.employee_1_stddev,
        simulation_time
    )
    employee2 = Employee(
        env, logger, 2,
        args.employee_2_mean, args.employee_2_stddev,
        simulation_time
    )
    
    # Create queue
    queue = Queue(env, logger, [employee1, employee2])
    
    # Create client generator
    generator = ClientGenerator(
        env, logger, queue,
        args.client_mean, args.client_stddev,
        simulation_time
    )
    
    # Run simulation
    env.run(until=simulation_time)
    
    # Print all events
    logger.print_events()


def main():
    """Main entry point"""
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
    
    run_simulation(args)


if __name__ == "__main__":
    main()
