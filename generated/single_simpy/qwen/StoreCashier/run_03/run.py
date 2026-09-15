```python_code
import argparse
import json
import math
import random
import sys
from datetime import datetime, timedelta

def format_time(seconds):
    """Convert seconds to HH:MM:SS:mmm format"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millisecs = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{millisecs:03d}"

class Event:
    def __init__(self, time, event, entity_type, entity, payload):
        self.time = time
        self.event = event
        self.entity_type = entity_type
        self.entity = entity
        self.payload = payload

    def to_json(self):
        return {
            "time": self.time,
            "time_str": format_time(self.time),
            "event": self.event,
            "entity_type": self.entity_type,
            "entity": self.entity,
            "payload": self.payload
        }

class Client:
    def __init__(self, client_id, arrival_time):
        self.client_id = client_id
        self.arrival_time = arrival_time

class Employee:
    def __init__(self, employee_id, mean, stddev):
        self.employee_id = employee_id
        self.mean = mean
        self.stddev = stddev
        self.is_available = True
        self.current_client = None
        self.service_start_time = None

    def get_service_duration(self):
        if self.stddev == 0:
            return self.mean
        # Generate normally distributed service duration
        duration = random.gauss(self.mean, self.stddev)
        # Clamp to valid range
        min_duration = self.mean - 3 * self.stddev
        max_duration = self.mean + 3 * self.stddev
        return max(min_duration, min(max_duration, duration))

class ClientGenerator:
    def __init__(self, mean, stddev):
        self.mean = mean
        self.stddev = stddev
        self.client_id_counter = 1

    def get_interarrival_time(self):
        # Generate normally distributed interarrival time
        interval = random.gauss(self.mean, self.stddev)
        # Clamp to valid range
        min_interval = 0
        max_interval = self.mean + 5 * self.stddev
        return max(min_interval, min(max_interval, interval))

class StoreSimulation:
    def __init__(self, 
                 simulation_time,
                 client_mean, 
                 client_stddev,
                 employee_1_mean, 
                 employee_1_stddev,
                 employee_2_mean, 
                 employee_2_stddev):
        self.simulation_time = simulation_time
        self.client_generator = ClientGenerator(client_mean, client_stddev)
        self.employee_1 = Employee(1, employee_1_mean, employee_1_stddev)
        self.employee_2 = Employee(2, employee_2_mean, employee_2_stddev)
        self.queue = []
        self.events = []
        self.current_time = 0.0
        self.client_id_counter = 1

    def add_event(self, time, event, entity_type, entity, payload):
        if time <= self.simulation_time:
            self.events.append(Event(time, event, entity_type, entity, payload))

    def process_client_arrival(self, arrival_time):
        # Create new client
        client = Client(self.client_id_counter, arrival_time)
        self.client_id_counter += 1
        
        # Add client to queue
        self.queue.append(client)
        
        # Emit client generated event
        self.add_event(
            arrival_time,
            "client_generated",
            "client_generator",
            "ClientGenerator",
            {"client_id": client.client_id, "arrival_time": arrival_time}
        )
        
        # Try to pair client with employee
        self.try_to_pair_client()

    def try_to_pair_client(self):
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
            
        # Take the first client from queue
        client = self.queue.pop(0)
        
        # Assign to first available employee
        employee = available_employees[0]
        
        # Mark employee as busy
        employee.is_available = False
        employee.current_client = client
        employee.service_start_time = self.current_time
        
        # Emit client paired event
        self.add_event(
            self.current_time,
            "client_paired",
            "queue",
            "Queue",
            {
                "client_id": client.client_id,
                "employee_id": employee.employee_id,
                "paired_time": self.current_time
            }
        )
        
        # Schedule service completion
        service_duration = employee.get_service_duration()
        completion_time = self.current_time + service_duration
        
        # Emit employee available event at completion time
        self.add_event(
            completion_time,
            "client_served",
            "employee",
            f"Employee_{employee.employee_id}",
            {
                "client_id": client.client_id,
                "employee_id": employee.employee_id,
                "arrived": client.arrival_time,
                "dispatched": completion_time,
                "delay": completion_time - client.arrival_time
            }
        )
        
        # Schedule employee availability
        self.add_event(
            completion_time,
            "employee_available",
            "employee",
            f"Employee_{employee.employee_id}",
            {"employee_id": employee.employee_id}
        )

    def run(self):
        # Initial employee availability
        self.add_event(
            0.0,
            "employee_available",
            "employee",
            "Employee_1",
            {"employee_id": 1}
        )
        self.add_event(
            0.0,
            "employee_available",
            "employee",
            "Employee_2",
            {"employee_id": 2}
        )
        
        # Initial client arrival
        self.process_client_arrival(0.0)
        
        # Generate clients until simulation time
        next_arrival_time = 0.0
        while self.current_time <= self.simulation_time:
            # Advance to next client arrival
            interarrival = self.client_generator.get_interarrival_time()
            next_arrival_time += interarrival
            
            # If we're past simulation time, stop
            if next_arrival_time > self.simulation_time:
                break
                
            self.current_time = next_arrival_time
            self.process_client_arrival(self.current_time)
            
            # Process any events that happen at this time
            self.events.sort(key=lambda e: e.time)
            
        # Sort all events by time
        self.events.sort(key=lambda e: e.time)
        
        # Output all events as JSONL
        for event in self.events:
            print(json.dumps(event.to_json()))

def parse_time_string(time_str):
    """Parse HH:MM:SS:mmm format to seconds"""
    hours, minutes, seconds, milliseconds = map(int, time_str.split(':'))
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulation_time', default='00:05:00:000')
    parser.add_argument('--client_mean', type=float, default=10.0)
    parser.add_argument('--client_stddev', type=float, default=5.0)
    parser.add_argument('--employee_1_mean', type=float, default=20.0)
    parser.add_argument('--employee_1_stddev', type=float, default=0.0)
    parser.add_argument('--employee_2_mean', type=float, default=30.0)
    parser.add_argument('--employee_2_stddev', type=float, default=4.0)
    
    args = parser.parse_args()
    
    # Parse simulation time
    simulation_time = parse_time_string(args.simulation_time)
    
    # Create and run simulation
    sim = StoreSimulation(
        simulation_time,
        args.client_mean,
        args.client_stddev,
        args.employee_1_mean,
        args.employee_1_stddev,
        args.employee_2_mean,
        args.employee_2_stddev
    )
    
    sim.run()

if __name__ == "__main__":
    main()
</python_code>
```