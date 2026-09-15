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


class Event:
    """Represents an event in the simulation"""
    def __init__(self, time: float, event_type: str, entity_type: str, entity: str, payload: dict):
        self.time = time
        self.event_type = event_type
        self.entity_type = entity_type
        self.entity = entity
        self.payload = payload

    def to_jsonl(self) -> str:
        """Convert event to JSONL format"""
        # Convert time to HH:MM:SS:mmm format
        time_str = format_time(self.time)
        
        event_dict = {
            "time": self.time,
            "time_str": time_str,
            "event": self.event_type,
            "entity_type": self.entity_type,
            "entity": self.entity,
            "payload": self.payload
        }
        return json.dumps(event_dict)


def format_time(seconds: float) -> str:
    """Format seconds into HH:MM:SS:mmm format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millisecs = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{millisecs:03d}"


class Client:
    """Represents a client in the simulation"""
    def __init__(self, client_id: int, arrival_time: float):
        self.client_id = client_id
        self.arrival_time = arrival_time


class Employee:
    """Represents an employee in the simulation"""
    def __init__(self, employee_id: int, mean_service_time: float, stddev_service_time: float):
        self.employee_id = employee_id
        self.mean_service_time = mean_service_time
        self.stddev_service_time = stddev_service_time
        self.is_available = True
        self.current_client = None
        self.service_start_time = None


class CashierSimulation:
    """Main simulation class"""
    def __init__(self, 
                 simulation_time: str = "00:05:00:000",
                 client_mean: float = 10.0,
                 client_stddev: float = 5.0,
                 employee_1_mean: float = 20.0,
                 employee_1_stddev: float = 0.0,
                 employee_2_mean: float = 30.0,
                 employee_2_stddev: float = 4.0,
                 seed: Optional[int] = None):
        self.simulation_time = parse_time_string(simulation_time)
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.employee_1_mean = employee_1_mean
        self.employee_1_stddev = employee_1_stddev
        self.employee_2_mean = employee_2_mean
        self.employee_2_stddev = employee_2_stddev
        self.seed = seed
        
        # Initialize simulation environment
        self.env = simpy.Environment()
        
        # Initialize entities
        self.client_generator = None
        self.queue = []
        self.employee_1 = Employee(1, employee_1_mean, employee_1_stddev)
        self.employee_2 = Employee(2, employee_2_mean, employee_2_stddev)
        
        # Client ID counter
        self.client_id_counter = 1
        
        # Events list for output
        self.events = []
        
        # Set random seed if provided
        if seed is not None:
            random.seed(seed)

    def generate_client(self):
        """Generate clients according to the specified distribution"""
        # First client is generated at t=0.0
        yield self.env.timeout(0.0)
        
        while self.env.now < self.simulation_time:
            # Generate inter-arrival time
            if self.client_stddev == 0:
                inter_arrival = self.client_mean
            else:
                # Ensure inter-arrival time is within bounds
                inter_arrival = max(0, random.gauss(self.client_mean, self.client_stddev))
                # Clamp to allowed range
                max_interval = self.client_mean + 5 * self.client_stddev
                inter_arrival = min(inter_arrival, max_interval)
            
            # Schedule next client
            yield self.env.timeout(inter_arrival)
            
            # Create new client
            client = Client(self.client_id_counter, self.env.now)
            self.client_id_counter += 1
            
            # Emit client_generated event
            event = Event(
                time=self.env.now,
                event_type="client_generated",
                entity_type="client_generator",
                entity="ClientGenerator",
                payload={
                    "client_id": client.client_id,
                    "arrival_time": client.arrival_time
                }
            )
            self.events.append(event)
            
            # Add client to queue
            self.queue.append(client)
            
            # Try to pair client with available employee
            self._try_pair_client()

    def _try_pair_client(self):
        """Try to pair an available client with an available employee"""
        if not self.queue:
            return
            
        # Check if any employee is available
        available_employees = []
        if self.employee_1.is_available:
            available_employees.append(self.employee_1)
        if self.employee_2.is_available:
            available_employees.append(self.employee_2)
            
        if not available_employees:
            return
            
        # Get the oldest client (FIFO)
        client = self.queue[0]
        
        # Assign to first available employee
        employee = available_employees[0]
        
        # Remove client from queue
        self.queue.pop(0)
        
        # Mark employee as busy
        employee.is_available = False
        employee.current_client = client
        employee.service_start_time = self.env.now
        
        # Emit client_paired event
        event = Event(
            time=self.env.now,
            event_type="client_paired",
            entity_type="queue",
            entity="Queue",
            payload={
                "client_id": client.client_id,
                "employee_id": employee.employee_id,
                "paired_time": self.env.now
            }
        )
        self.events.append(event)
        
        # Start service
        self.env.process(self._serve_client(employee, client))

    def _serve_client(self, employee: Employee, client: Client):
        """Serve a client"""
        # Calculate service duration
        if employee.stddev_service_time == 0:
            service_duration = employee.mean_service_time
        else:
            # Ensure service duration is within bounds
            service_duration = max(
                employee.mean_service_time - 3 * employee.stddev_service_time,
                min(
                    employee.mean_service_time + 3 * employee.stddev_service_time,
                    random.gauss(employee.mean_service_time, employee.stddev_service_time)
                )
            )
        
        # Wait for service to complete
        yield self.env.timeout(service_duration)
        
        # Mark employee as available
        employee.is_available = True
        employee.current_client = None
        employee.service_start_time = None
        
        # Emit employee_available event
        event = Event(
            time=self.env.now,
            event_type="employee_available",
            entity_type="employee",
            entity=f"Employee_{employee.employee_id}",
            payload={
                "employee_id": employee.employee_id
            }
        )
        self.events.append(event)
        
        # Emit client_served event
        delay = self.env.now - client.arrival_time
        event = Event(
            time=self.env.now,
            event_type="client_served",
            entity_type="employee",
            entity=f"Employee_{employee.employee_id}",
            payload={
                "client_id": client.client_id,
                "employee_id": employee.employee_id,
                "arrived": client.arrival_time,
                "dispatched": self.env.now,
                "delay": delay
            }
        )
        self.events.append(event)
        
        # Try to pair next client
        self._try_pair_client()

    def run(self):
        """Run the simulation"""
        # Start client generator
        self.env.process(self.generate_client())
        
        # Initialize employees as available
        event1 = Event(
            time=0.0,
            event_type="employee_available",
            entity_type="employee",
            entity="Employee_1",
            payload={"employee_id": 1}
        )
        self.events.append(event1)
        
        event2 = Event(
            time=0.0,
            event_type="employee_available",
            entity_type="employee",
            entity="Employee_2",
            payload={"employee_id": 2}
        )
        self.events.append(event2)
        
        # Run simulation
        self.env.run(until=self.simulation_time)
        
        # Sort events by time
        self.events.sort(key=lambda x: x.time)
        
        # Print events in JSONL format
        for event in self.events:
            print(event.to_jsonl())


def parse_time_string(time_str: str) -> float:
    """Parse time string in HH:MM:SS:mmm format to seconds"""
    try:
        hours, minutes, seconds, millisecs = map(int, time_str.split(':'))
        return hours * 3600 + minutes * 60 + seconds + millisecs / 1000
    except ValueError:
        raise ValueError(f"Invalid time format: {time_str}. Expected HH:MM:SS:mmm")


def main():
    """Main function to parse arguments and run simulation"""
    parser = argparse.ArgumentParser(description="Two-Employee Store Cashier Simulation")
    
    parser.add_argument("--simulation_time", 
                       default="00:05:00:000",
                       help="Total simulation horizon in HH:MM:SS:mmm format. Default: 00:05:00:000")
    
    parser.add_argument("--client_mean", 
                       type=float, 
                       default=10.0,
                       help="Client inter-arrival mean. Default: 10.0")
    
    parser.add_argument("--client_stddev", 
                       type=float, 
                       default=5.0,
                       help="Client inter-arrival standard deviation. Default: 5.0")
    
    parser.add_argument("--employee_1_mean", 
                       type=float, 
                       default=20.0,
                       help="Employee 1 service mean. Default: 20.0")
    
    parser.add_argument("--employee_1_stddev", 
                       type=float, 
                       default=0.0,
                       help="Employee 1 service standard deviation. Default: 0.0")
    
    parser.add_argument("--employee_2_mean", 
                       type=float, 
                       default=30.0,
                       help="Employee 2 service mean. Default: 30.0")
    
    parser.add_argument("--employee_2_stddev", 
                       type=float, 
                       default=4.0,
                       help="Employee 2 service standard deviation. Default: 4.0")
    
    parser.add_argument("--seed", 
                       type=int, 
                       help="Random seed for reproducibility")
    
    args = parser.parse_args()
    
    # Create and run simulation
    simulation = CashierSimulation(
        simulation_time=args.simulation_time,
        client_mean=args.client_mean,
        client_stddev=args.client_stddev,
        employee_1_mean=args.employee_1_mean,
        employee_1_stddev=args.employee_1_stddev,
        employee_2_mean=args.employee_2_mean,
        employee_2_stddev=args.employee_2_stddev,
        seed=args.seed
    )
    
    simulation.run()


if __name__ == "__main__":
    main()