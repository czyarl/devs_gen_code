#!/usr/bin/env python3
"""
Two-Employee Store Cashier Simulation

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
    """Parse time string in HH:MM:SS:mmm format to seconds."""
    parts = time_str.split(':')
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {time_str}")
    hours, minutes, seconds, milliseconds = map(int, parts)
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def format_time_str(time: float) -> str:
    """Format time in seconds to HH:MM:SS:mmm format."""
    total_ms = int(time * 1000)
    hours = total_ms // (3600 * 1000)
    remaining = total_ms % (3600 * 1000)
    minutes = remaining // (60 * 1000)
    remaining = remaining % (60 * 1000)
    seconds = remaining // 1000
    milliseconds = remaining % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"


class EventLogger:
    """Logger for simulation events in JSONL format."""
    
    def __init__(self):
        self.events: List[Dict] = []
    
    def log(self, time: float, event: str, entity_type: str, entity: str, payload: Dict):
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
        self.client_counter = 0
        self.queue: List[Client] = []
        self.employees: Dict[int, Dict] = {
            1: {"available": True, "current_client": None},
            2: {"available": True, "current_client": None}
        }
    
    def sample_client_interval(self) -> float:
        """Sample client inter-arrival time from normal distribution."""
        # Sample from normal distribution and clamp to valid range
        interval = random.gauss(self.client_mean, self.client_stddev)
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
        min_duration = mean - 3 * stddev
        max_duration = mean + 3 * stddev
        return max(min_duration, min(duration, max_duration))
    
    def generate_client(self, env: simpy.Environment):
        """Generate clients over time."""
        while True:
            # Check if we're still within simulation time
            if env.now >= self.simulation_time:
                break
            
            # Generate a new client
            self.client_counter += 1
            client = Client(self.client_counter, env.now)
            
            # Log client_generated event
            self.logger.log(
                time=env.now,
                event="client_generated",
                entity_type="client_generator",
                entity="ClientGenerator",
                payload={"client_id": client.client_id, "arrival_time": client.arrival_time}
            )
            
            # Add to queue
            self.queue.append(client)
            
            # Try to pair with available employee
            self.try_pair_client(env)
            
            # Schedule next client generation
            interval = self.sample_client_interval()
            next_arrival = env.now + interval
            if next_arrival > self.simulation_time:
                # Don't schedule next client beyond simulation time
                break
            yield env.timeout(interval)
    
    def try_pair_client(self, env: simpy.Environment):
        """Try to pair a waiting client with an available employee."""
        # Find available employees
        available_employees = [
            eid for eid, emp in self.employees.items() 
            if emp["available"]
        ]
        
        if not available_employees or not self.queue:
            return
        
        # Get the first client in FIFO order
        client = self.queue.pop(0)
        
        # Assign to first available employee
        employee_id = available_employees[0]
        self.employees[employee_id]["available"] = False
        self.employees[employee_id]["current_client"] = client
        
        client.paired_time = env.now
        client.employee_id = employee_id
        
        # Log client_paired event
        self.logger.log(
            time=env.now,
            event="client_paired",
            entity_type="queue",
            entity="Queue",
            payload={
                "client_id": client.client_id,
                "employee_id": employee_id,
                "paired_time": client.paired_time
            }
        )
        
        # Schedule service completion
        service_duration = self.sample_service_duration(employee_id)
        env.process(self.complete_service(env, employee_id, service_duration))
    
    def complete_service(self, env: simpy.Environment, employee_id: int, duration: float):
        """Complete service for a client."""
        # Wait for service to complete
        yield env.timeout(duration)
        
        # Check if we're still within simulation time
        if env.now > self.simulation_time:
            return
        
        # Get the client
        client = self.employees[employee_id]["current_client"]
        if client is None:
            return
        
        # Log client_served event
        delay = env.now - client.arrival_time
        self.logger.log(
            time=env.now,
            event="client_served",
            entity_type="employee",
            entity=f"Employee_{employee_id}",
            payload={
                "client_id": client.client_id,
                "employee_id": employee_id,
                "arrived": client.arrival_time,
                "dispatched": env.now,
                "delay": delay
            }
        )
        
        # Mark employee as available
        self.employees[employee_id]["available"] = True
        self.employees[employee_id]["current_client"] = None
        
        # Log employee_available event
        self.logger.log(
            time=env.now,
            event="employee_available",
            entity_type="employee",
            entity=f"Employee_{employee_id}",
            payload={"employee_id": employee_id}
        )
        
        # Try to pair with next waiting client
        self.try_pair_client(env)
    
    def run(self):
        """Run the simulation."""
        env = simpy.Environment()
        
        # Log initial employee availability
        self.logger.log(
            time=0.0,
            event="employee_available",
            entity_type="employee",
            entity="Employee_1",
            payload={"employee_id": 1}
        )
        self.logger.log(
            time=0.0,
            event="employee_available",
            entity_type="employee",
            entity="Employee_2",
            payload={"employee_id": 2}
        )
        
        # Start client generation
        env.process(self.generate_client(env))
        
        # Run simulation
        env.run(until=self.simulation_time)
        
        # Print all events
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
        help="Total simulation horizon in HH:MM:SS:mmm format"
    )
    
    parser.add_argument(
        "--client_mean",
        type=float,
        default=10.0,
        help="Client inter-arrival mean"
    )
    
    parser.add_argument(
        "--client_stddev",
        type=float,
        default=5.0,
        help="Client inter-arrival stddev"
    )
    
    parser.add_argument(
        "--employee_1_mean",
        type=float,
        default=20.0,
        help="Employee 1 service mean"
    )
    
    parser.add_argument(
        "--employee_1_stddev",
        type=float,
        default=0.0,
        help="Employee 1 service stddev"
    )
    
    parser.add_argument(
        "--employee_2_mean",
        type=float,
        default=30.0,
        help="Employee 2 service mean"
    )
    
    parser.add_argument(
        "--employee_2_stddev",
        type=float,
        default=4.0,
        help="Employee 2 service stddev"
    )
    
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Random seed for reproducibility"
    )
    
    args = parser.parse_args()
    
    # Parse simulation time
    try:
        sim_time = parse_time_str(args.simulation_time)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    
    # Create and run simulation
    sim = StoreSimulation(
        simulation_time=sim_time,
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
