#!/usr/bin/env python3
"""
Two-Employee Store Cashier Simulation
"""

import argparse
import json
import random
from datetime import datetime, timedelta
import sys


class Event:
    def __init__(self, time, event_type, entity_type, entity, payload):
        self.time = time
        self.event_type = event_type
        self.entity_type = entity_type
        self.entity = entity
        self.payload = payload
    
    def to_jsonl(self):
        # Convert time to HH:MM:SS:mmm format
        hours = int(self.time // 3600)
        minutes = int((self.time % 3600) // 60)
        seconds = int(self.time % 60)
        milliseconds = int((self.time % 1) * 1000)
        
        time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"
        
        return json.dumps({
            "time": self.time,
            "time_str": time_str,
            "event": self.event_type,
            "entity_type": self.entity_type,
            "entity": self.entity,
            "payload": self.payload
        })


class SimulatedTime:
    """Deterministic simulation time manager"""
    def __init__(self, start_time=0.0):
        self.current_time = start_time
    
    def get_time(self):
        return self.current_time
    
    def advance_time(self, delta):
        self.current_time += delta


class ClientGenerator:
    def __init__(self, sim_time, client_mean, client_stddev, seed=None):
        self.sim_time = sim_time
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.seed = seed
        self.client_id_counter = 1
        
        if seed is not None:
            random.seed(seed)
    
    def generate_client(self):
        # Generate inter-arrival time within bounds
        if self.client_stddev == 0:
            interval = self.client_mean
        else:
            # Ensure interval is within valid range: [0, client_mean + 5 * client_stddev]
            while True:
                interval = random.gauss(self.client_mean, self.client_stddev)
                if 0 <= interval <= self.client_mean + 5 * self.client_stddev:
                    break
        
        arrival_time = self.sim_time.get_time() + interval
        client_id = self.client_id_counter
        self.client_id_counter += 1
        
        return client_id, arrival_time


class Employee:
    def __init__(self, emp_id, mean_service, stddev_service):
        self.id = emp_id
        self.mean_service = mean_service
        self.stddev_service = stddev_service
        self.is_available = True
        self.current_client = None
        self.service_start_time = None
    
    def get_service_duration(self):
        if self.stddev_service == 0:
            return self.mean_service
        else:
            # Ensure duration is within valid range: [mean - 3*stddev, mean + 3*stddev]
            while True:
                duration = random.gauss(self.mean_service, self.stddev_service)
                if self.mean_service - 3 * self.stddev_service <= duration <= self.mean_service + 3 * self.stddev_service:
                    return duration


class Queue:
    def __init__(self):
        self.waiting_clients = []
    
    def add_client(self, client_id, arrival_time):
        self.waiting_clients.append({"client_id": client_id, "arrival_time": arrival_time})
    
    def remove_client(self):
        if self.waiting_clients:
            return self.waiting_clients.pop(0)
        return None
    
    def is_empty(self):
        return len(self.waiting_clients) == 0


class CashierSystem:
    def __init__(self, sim_time, client_mean, client_stddev, 
                 emp1_mean, emp1_stddev, emp2_mean, emp2_stddev, seed=None):
        self.sim_time = sim_time
        self.client_generator = ClientGenerator(sim_time, client_mean, client_stddev, seed)
        self.employee1 = Employee(1, emp1_mean, emp1_stddev)
        self.employee2 = Employee(2, emp2_mean, emp2_stddev)
        self.queue = Queue()
        self.events = []
        self.simulation_horizon = None
        self.client_arrival_times = {}  # Track arrival times for each client
        
        # Initialize employees as available
        self.events.append(Event(
            self.sim_time.get_time(),
            "employee_available",
            "employee",
            "Employee_1",
            {"employee_id": 1}
        ))
        self.events.append(Event(
            self.sim_time.get_time(),
            "employee_available",
            "employee",
            "Employee_2",
            {"employee_id": 2}
        ))
    
    def set_simulation_horizon(self, hours, minutes, seconds, milliseconds):
        self.simulation_horizon = (
            hours * 3600 + 
            minutes * 60 + 
            seconds + 
            milliseconds / 1000.0
        )
    
    def is_simulation_finished(self):
        if self.simulation_horizon is None:
            return False
        return self.sim_time.get_time() > self.simulation_horizon
    
    def process_event(self, event):
        self.events.append(event)
    
    def run_simulation(self):
        # Generate first client at t=0.0
        client_id, arrival_time = self.client_generator.generate_client()
        self.client_arrival_times[client_id] = arrival_time
        self.process_event(Event(
            arrival_time,
            "client_generated",
            "client_generator",
            "ClientGenerator",
            {"client_id": client_id, "arrival_time": arrival_time}
        ))
        
        # Add to queue
        self.queue.add_client(client_id, arrival_time)
        
        # Continue processing events until simulation horizon
        while not self.is_simulation_finished():
            # Check if we have clients in queue and available employees
            if not self.queue.is_empty():
                # Try to pair a client with an available employee
                if self.employee1.is_available:
                    client_info = self.queue.remove_client()
                    self.pair_client_with_employee(client_info, self.employee1)
                elif self.employee2.is_available:
                    client_info = self.queue.remove_client()
                    self.pair_client_with_employee(client_info, self.employee2)
            
            # Check if any employee has finished serving
            if not self.employee1.is_available:
                service_duration = self.employee1.get_service_duration()
                if self.sim_time.get_time() >= self.employee1.service_start_time + service_duration:
                    self.complete_service(self.employee1)
            
            if not self.employee2.is_available:
                service_duration = self.employee2.get_service_duration()
                if self.sim_time.get_time() >= self.employee2.service_start_time + service_duration:
                    self.complete_service(self.employee2)
            
            # Generate next client if needed
            if not self.is_simulation_finished():
                client_id, arrival_time = self.client_generator.generate_client()
                self.client_arrival_times[client_id] = arrival_time
                self.process_event(Event(
                    arrival_time,
                    "client_generated",
                    "client_generator",
                    "ClientGenerator",
                    {"client_id": client_id, "arrival_time": arrival_time}
                ))
                
                # Add to queue
                self.queue.add_client(client_id, arrival_time)
        
        # Sort events by time
        self.events.sort(key=lambda x: x.time)
        
        # Print events
        for event in self.events:
            print(event.to_jsonl())


    def pair_client_with_employee(self, client_info, employee):
        client_id = client_info["client_id"]
        arrival_time = client_info["arrival_time"]
        paired_time = self.sim_time.get_time()
        
        # Mark employee as busy
        employee.is_available = False
        employee.current_client = client_id
        employee.service_start_time = paired_time
        
        # Emit pairing event
        self.process_event(Event(
            paired_time,
            "client_paired",
            "queue",
            "Queue",
            {
                "client_id": client_id,
                "employee_id": employee.id,
                "paired_time": paired_time
            }
        ))
    
    def complete_service(self, employee):
        client_id = employee.current_client
        dispatched_time = self.sim_time.get_time()
        service_duration = dispatched_time - employee.service_start_time
        delay = dispatched_time - self.client_arrival_times[client_id]
        
        # Mark employee as available
        employee.is_available = True
        employee.current_client = None
        employee.service_start_time = None
        
        # Emit service completion event
        self.process_event(Event(
            dispatched_time,
            "client_served",
            "employee",
            f"Employee_{employee.id}",
            {
                "client_id": client_id,
                "employee_id": employee.id,
                "arrived": self.client_arrival_times[client_id],
                "dispatched": dispatched_time,
                "delay": delay
            }
        ))
        
        # Emit employee availability event
        self.process_event(Event(
            dispatched_time,
            "employee_available",
            "employee",
            f"Employee_{employee.id}",
            {"employee_id": employee.id}
        ))


def parse_time_string(time_str):
    """Parse time string in HH:MM:SS:mmm format"""
    try:
        hms, ms = time_str.rsplit(':', 1)
        hours, minutes, seconds = map(int, hms.split(':'))
        milliseconds = int(ms)
        return hours, minutes, seconds, milliseconds
    except Exception:
        raise ValueError("Invalid time format. Expected HH:MM:SS:mmm")


def main():
    parser = argparse.ArgumentParser(description="Two-Employee Store Cashier Simulation")
    
    parser.add_argument('--simulation_time', type=str, default="00:05:00:000",
                        help='Total simulation horizon in HH:MM:SS:mmm format. Default "00:05:00:000"')
    
    parser.add_argument('--client_mean', type=float, default=10.0,
                        help='Client inter-arrival mean. Default 10.0')
    
    parser.add_argument('--client_stddev', type=float, default=5.0,
                        help='Client inter-arrival standard deviation. Default 5.0')
    
    parser.add_argument('--employee_1_mean', type=float, default=20.0,
                        help='Employee 1 service mean. Default 20.0')
    
    parser.add_argument('--employee_1_stddev', type=float, default=0.0,
                        help='Employee 1 service standard deviation. Default 0.0')
    
    parser.add_argument('--employee_2_mean', type=float, default=30.0,
                        help='Employee 2 service mean. Default 30.0')
    
    parser.add_argument('--employee_2_stddev', type=float, default=4.0,
                        help='Employee 2 service standard deviation. Default 4.0')
    
    parser.add_argument('--seed', type=int, default=None,
                        help='Random seed for reproducibility')
    
    args = parser.parse_args()
    
    # Parse simulation time
    hours, minutes, seconds, milliseconds = parse_time_string(args.simulation_time)
    
    # Create simulation time manager
    sim_time = SimulatedTime(0.0)
    
    # Create cashier system
    system = CashierSystem(
        sim_time,
        args.client_mean,
        args.client_stddev,
        args.employee_1_mean,
        args.employee_1_stddev,
        args.employee_2_mean,
        args.employee_2_stddev,
        args.seed
    )
    
    # Set simulation horizon
    system.set_simulation_horizon(hours, minutes, seconds, milliseconds)
    
    # Run simulation
    system.run_simulation()


if __name__ == "__main__":
    main()