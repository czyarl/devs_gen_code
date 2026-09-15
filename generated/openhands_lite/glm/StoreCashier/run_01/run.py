#!/usr/bin/env python3
"""Two-Employee Store Cashier Discrete Event Simulation"""

import argparse
import json
import random
import sys
from typing import List, Dict, Any
import simpy


def parse_time_str(time_str: str) -> float:
    """Parse HH:MM:SS:mmm format to seconds"""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def format_time_str(time: float) -> str:
    """Format seconds to HH:MM:SS:mmm"""
    total_ms = int(time * 1000)
    hours = total_ms // 3600000
    remaining = total_ms % 3600000
    minutes = remaining // 60000
    remaining = remaining % 60000
    seconds = remaining // 1000
    milliseconds = remaining % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"


class EventLogger:
    """Handles JSONL event logging"""
    
    def __init__(self):
        self.events: List[Dict[str, Any]] = []
    
    def log(self, time: float, event: str, entity_type: str, entity: str, payload: Dict[str, Any]):
        """Log an event"""
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
        """Print all events in JSONL format"""
        for event in self.events:
            print(json.dumps(event))


class StoreCashierSimulation:
    """Main simulation class for two-employee store cashier system"""
    
    def __init__(self, simulation_time: float, client_mean: float, client_stddev: float,
                 employee_1_mean: float, employee_1_stddev: float,
                 employee_2_mean: float, employee_2_stddev: float,
                 seed: int = None):
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
        self.queue: List[Dict[str, Any]] = []
        self.employees = {
            1: {"available": True, "current_client": None},
            2: {"available": True, "current_client": None}
        }
        self.paired_clients: Dict[int, float] = {}  # client_id -> paired_time
        self.client_arrival_times: Dict[int, float] = {}  # client_id -> arrival_time
    
    def sample_client_interval(self) -> float:
        """Sample inter-arrival time for clients"""
        max_interval = self.client_mean + 5 * self.client_stddev
        interval = random.gauss(self.client_mean, self.client_stddev)
        return max(0.0, min(interval, max_interval))
    
    def sample_service_duration(self, employee_id: int) -> float:
        """Sample service duration for an employee"""
        if employee_id == 1:
            mean = self.employee_1_mean
            stddev = self.employee_1_stddev
        else:
            mean = self.employee_2_mean
            stddev = self.employee_2_stddev
        
        if stddev == 0:
            return mean
        
        min_duration = mean - 3 * stddev
        max_duration = mean + 3 * stddev
        duration = random.gauss(mean, stddev)
        return max(min_duration, min(duration, max_duration))
    
    def generate_client(self, env: simpy.Environment):
        """Generate clients over time"""
        while True:
            self.client_counter += 1
            client_id = self.client_counter
            arrival_time = env.now
            
            self.logger.log(
                time=arrival_time,
                event="client_generated",
                entity_type="client_generator",
                entity="ClientGenerator",
                payload={"client_id": client_id, "arrival_time": arrival_time}
            )
            
            # Store client arrival time
            self.client_arrival_times[client_id] = arrival_time
            
            # Add client to queue
            self.queue.append({"client_id": client_id, "arrival_time": arrival_time})
            
            # Try to pair client with available employee
            self.try_pair_client(env)
            
            # Schedule next client generation
            interval = self.sample_client_interval()
            next_arrival = arrival_time + interval
            
            if next_arrival >= self.simulation_time:
                break
            
            yield env.timeout(interval)
    
    def try_pair_client(self, env: simpy.Environment):
        """Try to pair waiting clients with available employees"""
        while self.queue and (self.employees[1]["available"] or self.employees[2]["available"]):
            client = self.queue.pop(0)  # FIFO order
            client_id = client["client_id"]
            
            # Find available employee
            if self.employees[1]["available"]:
                employee_id = 1
            elif self.employees[2]["available"]:
                employee_id = 2
            else:
                # No available employee, put client back
                self.queue.insert(0, client)
                break
            
            # Pair client with employee
            paired_time = env.now
            self.employees[employee_id]["available"] = False
            self.employees[employee_id]["current_client"] = client_id
            self.paired_clients[client_id] = paired_time
            
            self.logger.log(
                time=paired_time,
                event="client_paired",
                entity_type="queue",
                entity="Queue",
                payload={"client_id": client_id, "employee_id": employee_id, "paired_time": paired_time}
            )
            
            # Schedule service completion
            service_duration = self.sample_service_duration(employee_id)
            env.process(self.complete_service(env, employee_id, client_id, service_duration))
    
    def complete_service(self, env: simpy.Environment, employee_id: int, client_id: int, service_duration: float):
        """Complete service for a client"""
        completion_time = env.now + service_duration
        
        if completion_time >= self.simulation_time:
            return
        
        yield env.timeout(service_duration)
        
        # Get client info
        arrived = self.client_arrival_times[client_id]
        dispatched = env.now
        delay = dispatched - arrived
        
        self.logger.log(
            time=dispatched,
            event="client_served",
            entity_type="employee",
            entity=f"Employee_{employee_id}",
            payload={
                "client_id": client_id,
                "employee_id": employee_id,
                "arrived": arrived,
                "dispatched": dispatched,
                "delay": delay
            }
        )
        
        # Mark employee as available
        self.employees[employee_id]["available"] = True
        self.employees[employee_id]["current_client"] = None
        
        self.logger.log(
            time=dispatched,
            event="employee_available",
            entity_type="employee",
            entity=f"Employee_{employee_id}",
            payload={"employee_id": employee_id}
        )
        
        # Try to pair next client
        self.try_pair_client(env)
    
    def run(self):
        """Run the simulation"""
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
    parser = argparse.ArgumentParser(description="Two-Employee Store Cashier Simulation")
    parser.add_argument(
        "--simulation_time",
        type=str,
        default="00:05:00:000",
        help="Total simulation horizon in HH:MM:SS:mmm format"
    )
    parser.add_argument("--client_mean", type=float, default=10.0, help="Client inter-arrival mean")
    parser.add_argument("--client_stddev", type=float, default=5.0, help="Client inter-arrival stddev")
    parser.add_argument("--employee_1_mean", type=float, default=20.0, help="Employee 1 service mean")
    parser.add_argument("--employee_1_stddev", type=float, default=0.0, help="Employee 1 service stddev")
    parser.add_argument("--employee_2_mean", type=float, default=30.0, help="Employee 2 service mean")
    parser.add_argument("--employee_2_stddev", type=float, default=4.0, help="Employee 2 service stddev")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    
    args = parser.parse_args()
    
    simulation_time = parse_time_str(args.simulation_time)
    
    sim = StoreCashierSimulation(
        simulation_time=simulation_time,
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
