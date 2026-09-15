#!/usr/bin/env python3

import argparse
import json
import random
import simpy
from collections import deque
from typing import Dict, List


def parse_time_str(time_str: str) -> float:
    """Parse time from HH:MM:SS:mmm format to seconds."""
    hh, mm, ss, mmm = map(int, time_str.split(':'))
    return hh * 3600 + mm * 60 + ss + mmm / 1000.0


def format_time_str(time: float) -> str:
    """Format time from seconds to HH:MM:SS:mmm format."""
    hours = int(time // 3600)
    time %= 3600
    minutes = int(time // 60)
    time %= 60
    seconds = int(time // 1)
    milliseconds = int((time % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"


def get_truncated_normal(mean: float, stddev: float, low: float, high: float) -> float:
    """Sample from a truncated normal-like distribution within bounds."""
    if stddev == 0:
        return mean
    while True:
        value = random.gauss(mean, stddev)
        if low <= value <= high:
            return value


class EventLogger:
    """Logger for simulation events."""
    
    def __init__(self, simulation_horizon: float):
        self.events: List[Dict] = []
        self.simulation_horizon = simulation_horizon
    
    def log_event(self, time: float, event: str, entity_type: str, entity: str, payload: Dict):
        """Log an event if it's within simulation horizon."""
        if time <= self.simulation_horizon:
            self.events.append({
                'time': time,
                'time_str': format_time_str(time),
                'event': event,
                'entity_type': entity_type,
                'entity': entity,
                'payload': payload
            })
    
    def print_events(self):
        """Print all events as JSONL."""
        events_sorted = sorted(self.events, key=lambda x: x['time'])
        for event in events_sorted:
            print(json.dumps(event))


class StoreCashierSimulation:
    """Simulation of a store cashier system."""
    
    def __init__(self, 
                 simulation_time: str,
                 client_mean: float,
                 client_stddev: float,
                 employee_1_mean: float,
                 employee_1_stddev: float,
                 employee_2_mean: float,
                 employee_2_stddev: float,
                 seed: int = None):
        
        self.simulation_horizon = parse_time_str(simulation_time)
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.employee_1_mean = employee_1_mean
        self.employee_1_stddev = employee_1_stddev
        self.employee_2_mean = employee_2_mean
        self.employee_2_stddev = employee_2_stddev
        
        if seed is not None:
            random.seed(seed)
        
        self.client_id_counter = 0
        self.client_info: Dict[int, Dict] = {}
        
        # FIFO queue for waiting clients
        self.waiting_queue = deque()
        
        self.logger = EventLogger(self.simulation_horizon)
    
    def generate_client_arrival_interval(self) -> float:
        """Generate client inter-arrival time."""
        low = 0.0
        high = self.client_mean + 5 * self.client_stddev
        return get_truncated_normal(self.client_mean, self.client_stddev, low, high)
    
    def generate_service_duration(self, employee_id: int) -> float:
        """Generate service duration for an employee."""
        if employee_id == 1:
            mean, stddev = self.employee_1_mean, self.employee_1_stddev
        else:
            mean, stddev = self.employee_2_mean, self.employee_2_stddev
        
        low = mean - 3 * stddev
        high = mean + 3 * stddev
        return get_truncated_normal(mean, stddev, low, high)
    
    def client_generator_process(self, env: simpy.Environment):
        """Generate clients over time."""
        # First client at t=0.0
        yield env.timeout(0.0)
        
        while True:
            self.client_id_counter += 1
            client_id = self.client_id_counter
            arrival_time = env.now
            
            self.client_info[client_id] = {
                'arrival_time': arrival_time,
                'paired_time': None,
                'employee_id': None
            }
            
            self.logger.log_event(
                time=arrival_time,
                event='client_generated',
                entity_type='client_generator',
                entity='ClientGenerator',
                payload={'client_id': client_id, 'arrival_time': arrival_time}
            )
            
            # Add to FIFO waiting queue
            self.waiting_queue.append(client_id)
            
            # Try to pair with available employee (FIFO order)
            self.try_pair_waiting_clients(env)
            
            # Schedule next client
            interval = self.generate_client_arrival_interval()
            yield env.timeout(interval)
    
    def try_pair_waiting_clients(self, env: simpy.Environment):
        """Try to pair waiting clients with available employees in FIFO order."""
        while self.waiting_queue:
            client_id = self.waiting_queue[0]  # Peek at first client in FIFO order
            
            # Check if any employee is available
            if not env.employee_1_busy and not env.employee_2_busy:
                # Both available, prefer Employee_1 for FIFO
                self.paired_client(env, client_id, 1)
            elif not env.employee_1_busy:
                # Only Employee_1 available
                self.paired_client(env, client_id, 1)
            elif not env.employee_2_busy:
                # Only Employee_2 available
                self.paired_client(env, client_id, 2)
            else:
                # No employees available, stop trying
                break
            # Only pair one client at a time to ensure strict FIFO
    
    def paired_client(self, env: simpy.Environment, client_id: int, employee_id: int):
        """Pair a client with an employee and start service."""
        # Remove from waiting queue (should be at front due to FIFO)
        if self.waiting_queue and self.waiting_queue[0] == client_id:
            self.waiting_queue.popleft()
        else:
            # Client not at front, shouldn't happen in FIFO
            return
        
        paired_time = env.now
        
        self.client_info[client_id]['paired_time'] = paired_time
        self.client_info[client_id]['employee_id'] = employee_id
        
        # Mark employee as busy
        if employee_id == 1:
            env.employee_1_busy = True
        else:
            env.employee_2_busy = True
        
        self.logger.log_event(
            time=paired_time,
            event='client_paired',
            entity_type='queue',
            entity='Queue',
            payload={
                'client_id': client_id,
                'employee_id': employee_id,
                'paired_time': paired_time
            }
        )
        
        # Start service process
        env.process(self.service_process(env, client_id, employee_id))
    
    def service_process(self, env: simpy.Environment, client_id: int, employee_id: int):
        """Simulate service for a client."""
        service_duration = self.generate_service_duration(employee_id)
        yield env.timeout(service_duration)
        
        dispatched = env.now
        arrival_time = self.client_info[client_id]['arrival_time']
        delay = dispatched - arrival_time
        
        self.logger.log_event(
            time=dispatched,
            event='client_served',
            entity_type='employee',
            entity=f'Employee_{employee_id}',
            payload={
                'client_id': client_id,
                'employee_id': employee_id,
                'arrived': arrival_time,
                'dispatched': dispatched,
                'delay': delay
            }
        )
        
        # Mark employee as available
        if employee_id == 1:
            env.employee_1_busy = False
        else:
            env.employee_2_busy = False
        
        # Log employee available event
        self.logger.log_event(
            time=dispatched,
            event='employee_available',
            entity_type='employee',
            entity=f'Employee_{employee_id}',
            payload={'employee_id': employee_id}
        )
        
        # Try to pair next waiting client (FIFO order)
        self.try_pair_waiting_clients(env)
    
    def run(self):
        """Run the simulation."""
        env = simpy.Environment()
        env.employee_1_busy = False
        env.employee_2_busy = False
        
        # Log initial employee availability at t=0.0
        self.logger.log_event(
            time=0.0,
            event='employee_available',
            entity_type='employee',
            entity='Employee_1',
            payload={'employee_id': 1}
        )
        self.logger.log_event(
            time=0.0,
            event='employee_available',
            entity_type='employee',
            entity='Employee_2',
            payload={'employee_id': 2}
        )
        
        # Start client generator
        env.process(self.client_generator_process(env))
        
        # Run simulation
        env.run(until=self.simulation_horizon)
        
        # Print events
        self.logger.print_events()


def main():
    parser = argparse.ArgumentParser(description='Two-Employee Store Cashier Simulation')
    parser.add_argument('--simulation_time', type=str, default='00:05:00:000',
                        help='Simulation horizon in HH:MM:SS:mmm format')
    parser.add_argument('--client_mean', type=float, default=10.0,
                        help='Mean client inter-arrival time (seconds)')
    parser.add_argument('--client_stddev', type=float, default=5.0,
                        help='Standard deviation of client inter-arrival time (seconds)')
    parser.add_argument('--employee_1_mean', type=float, default=20.0,
                        help='Mean service time for employee 1 (seconds)')
    parser.add_argument('--employee_1_stddev', type=float, default=0.0,
                        help='Standard deviation of service time for employee 1 (seconds)')
    parser.add_argument('--employee_2_mean', type=float, default=30.0,
                        help='Mean service time for employee 2 (seconds)')
    parser.add_argument('--employee_2_stddev', type=float, default=4.0,
                        help='Standard deviation of service time for employee 2 (seconds)')
    parser.add_argument('--seed', type=int, default=None,
                        help='Random seed for reproducibility')
    
    args = parser.parse_args()
    
    simulation = StoreCashierSimulation(
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


if __name__ == '__main__':
    main()