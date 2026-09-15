#!/usr/bin/env python3
"""
Two-Employee Store Cashier Simulation
"""

import argparse
import json
import random
from datetime import datetime, timedelta
import simpy


class StoreCashierSimulation:
    def __init__(self, client_mean=10.0, client_stddev=5.0, 
                 employee_1_mean=20.0, employee_1_stddev=0.0,
                 employee_2_mean=30.0, employee_2_stddev=4.0,
                 simulation_time="00:05:00:000"):
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.employee_1_mean = employee_1_mean
        self.employee_1_stddev = employee_1_stddev
        self.employee_2_mean = employee_2_mean
        self.employee_2_stddev = employee_2_stddev
        
        # Parse simulation time
        h, m, s, ms = map(int, simulation_time.split(':'))
        self.simulation_horizon = h * 3600 + m * 60 + s + ms / 1000.0
        
        # Simulation environment
        self.env = simpy.Environment()
        
        # Entities
        self.client_generator = None
        self.queue = []
        self.employee_1_busy = False
        self.employee_2_busy = False
        
        # Client tracking
        self.next_client_id = 1
        self.client_arrival_times = {}
        self.client_paired_times = {}
        
        # Event tracking
        self.events = []
        
    def format_time(self, time_value):
        """Convert simulation time to HH:MM:SS:mmm format"""
        hours = int(time_value // 3600)
        minutes = int((time_value % 3600) // 60)
        seconds = int(time_value % 60)
        milliseconds = int((time_value % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"
    
    def generate_client(self):
        """Generate clients according to the specified distribution"""
        while self.env.now < self.simulation_horizon:
            # Generate inter-arrival time
            if self.client_stddev == 0:
                interval = self.client_mean
            else:
                # Ensure interval is within bounds
                interval = max(0, random.normalvariate(self.client_mean, self.client_stddev))
                interval = min(interval, self.client_mean + 5 * self.client_stddev)
            
            yield self.env.timeout(interval)
            
            if self.env.now >= self.simulation_horizon:
                break
                
            # Create new client
            client_id = self.next_client_id
            self.next_client_id += 1
            
            # Record arrival time
            self.client_arrival_times[client_id] = self.env.now
            
            # Emit client generated event
            event = {
                "time": self.env.now,
                "time_str": self.format_time(self.env.now),
                "event": "client_generated",
                "entity_type": "client_generator",
                "entity": "ClientGenerator",
                "payload": {
                    "client_id": client_id,
                    "arrival_time": self.env.now
                }
            }
            self.events.append(event)
            print(json.dumps(event))
            
            # Add client to queue
            self.queue.append(client_id)
            
            # Try to pair client with available employee
            self._try_pair_client()
    
    def _try_pair_client(self):
        """Try to pair waiting clients with available employees"""
        if not self.queue:
            return
            
        # Check if any employee is available
        if not self.employee_1_busy:
            # Employee 1 is available
            client_id = self.queue.pop(0)
            self.employee_1_busy = True
            self.client_paired_times[client_id] = self.env.now
            self.env.process(self.serve_client(client_id, 1))
            return
            
        if not self.employee_2_busy:
            # Employee 2 is available
            client_id = self.queue.pop(0)
            self.employee_2_busy = True
            self.client_paired_times[client_id] = self.env.now
            self.env.process(self.serve_client(client_id, 2))
            return
    
    def serve_client(self, client_id, employee_id):
        """Serve a client with the specified employee"""
        # Determine service duration based on employee characteristics
        if employee_id == 1:
            if self.employee_1_stddev == 0:
                duration = self.employee_1_mean
            else:
                duration = max(self.employee_1_mean - 3 * self.employee_1_stddev,
                              min(random.normalvariate(self.employee_1_mean, self.employee_1_stddev),
                                  self.employee_1_mean + 3 * self.employee_1_stddev))
        else:  # employee_id == 2
            if self.employee_2_stddev == 0:
                duration = self.employee_2_mean
            else:
                duration = max(self.employee_2_mean - 3 * self.employee_2_stddev,
                              min(random.normalvariate(self.employee_2_mean, self.employee_2_stddev),
                                  self.employee_2_mean + 3 * self.employee_2_stddev))
        
        # Wait for service to complete
        yield self.env.timeout(duration)
        
        # Service completed
        dispatched_time = self.env.now
        delay = dispatched_time - self.client_arrival_times[client_id]
        
        # Emit client served event
        event = {
            "time": dispatched_time,
            "time_str": self.format_time(dispatched_time),
            "event": "client_served",
            "entity_type": "employee",
            "entity": f"Employee_{employee_id}",
            "payload": {
                "client_id": client_id,
                "employee_id": employee_id,
                "arrived": self.client_arrival_times[client_id],
                "dispatched": dispatched_time,
                "delay": delay
            }
        }
        self.events.append(event)
        print(json.dumps(event))
        
        # Emit employee available event
        event = {
            "time": dispatched_time,
            "time_str": self.format_time(dispatched_time),
            "event": "employee_available",
            "entity_type": "employee",
            "entity": f"Employee_{employee_id}",
            "payload": {
                "employee_id": employee_id
            }
        }
        self.events.append(event)
        print(json.dumps(event))
        
        # Mark employee as available
        if employee_id == 1:
            self.employee_1_busy = False
        else:
            self.employee_2_busy = False
        
        # Try to pair remaining clients
        self._try_pair_client()
    
    def run(self):
        """Run the simulation"""
        # Start client generator
        self.env.process(self.generate_client())
        
        # Emit initial employee availability events
        event1 = {
            "time": 0.0,
            "time_str": "00:00:00:000",
            "event": "employee_available",
            "entity_type": "employee",
            "entity": "Employee_1",
            "payload": {
                "employee_id": 1
            }
        }
        self.events.append(event1)
        print(json.dumps(event1))
        
        event2 = {
            "time": 0.0,
            "time_str": "00:00:00:000",
            "event": "employee_available",
            "entity_type": "employee",
            "entity": "Employee_2",
            "payload": {
                "employee_id": 2
            }
        }
        self.events.append(event2)
        print(json.dumps(event2))
        
        # Run simulation
        self.env.run(until=self.simulation_horizon)


def main():
    parser = argparse.ArgumentParser(description='Two-Employee Store Cashier Simulation')
    parser.add_argument('--simulation_time', type=str, default="00:05:00:000",
                        help='Total simulation horizon in HH:MM:SS:mmm format (default: 00:05:00:000)')
    parser.add_argument('--client_mean', type=float, default=10.0,
                        help='Client inter-arrival mean (default: 10.0)')
    parser.add_argument('--client_stddev', type=float, default=5.0,
                        help='Client inter-arrival standard deviation (default: 5.0)')
    parser.add_argument('--employee_1_mean', type=float, default=20.0,
                        help='Employee 1 service mean (default: 20.0)')
    parser.add_argument('--employee_1_stddev', type=float, default=0.0,
                        help='Employee 1 service standard deviation (default: 0.0)')
    parser.add_argument('--employee_2_mean', type=float, default=30.0,
                        help='Employee 2 service mean (default: 30.0)')
    parser.add_argument('--employee_2_stddev', type=float, default=4.0,
                        help='Employee 2 service standard deviation (default: 4.0)')
    parser.add_argument('--seed', type=int, help='Random seed for reproducibility')
    
    args = parser.parse_args()
    
    # Set random seed if provided
    if args.seed is not None:
        random.seed(args.seed)
    
    # Create and run simulation
    simulation = StoreCashierSimulation(
        client_mean=args.client_mean,
        client_stddev=args.client_stddev,
        employee_1_mean=args.employee_1_mean,
        employee_1_stddev=args.employee_1_stddev,
        employee_2_mean=args.employee_2_mean,
        employee_2_stddev=args.employee_2_stddev,
        simulation_time=args.simulation_time
    )
    
    simulation.run()


if __name__ == "__main__":
    main()