import argparse
import heapq
import json
import random
import sys
from collections import deque
from typing import Dict, Deque

def format_time(seconds: float) -> str:
    """Formats simulation time in seconds to HH:MM:SS:mmm string."""
    total_ms = int(seconds * 1000)
    ms = total_ms % 1000
    total_seconds = total_ms // 1000
    s = total_seconds % 60
    total_minutes = total_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"

def parse_time_to_seconds(time_str: str) -> float:
    """Parses HH:MM:SS:mmm string to simulation time in seconds."""
    parts = time_str.split(':')
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {time_str}")
    h, m, s, ms = map(int, parts)
    return h * 3600 + m * 60 + s + ms / 1000.0

class Simulation:
    def __init__(self, args):
        # Parse simulation horizon
        self.sim_time = parse_time_to_seconds(args.simulation_time)
        
        # Store parameters
        self.client_mean = args.client_mean
        self.client_stddev = args.client_stddev
        self.emp1_mean = args.employee_1_mean
        self.emp1_stddev = args.employee_1_stddev
        self.emp2_mean = args.employee_2_mean
        self.emp2_stddev = args.employee_2_stddev
        
        # Set seed if provided
        if hasattr(args, 'seed') and args.seed is not None:
            random.seed(args.seed)
        
        # Simulation State
        self.current_time = 0.0
        self.client_id_counter = 1
        self.waiting_queue: Deque[int] = deque()
        self.client_arrival_times: Dict[int, float] = {}
        
        # Employee State
        self.employees = {
            1: {"available": True, "name": "Employee_1"},
            2: {"available": True, "name": "Employee_2"}
        }
        
        # Event Queue (min-heap)
        self.event_heap = []
        heapq.heapify(self.event_heap)
        
        # Schedule initial events
        heapq.heappush(self.event_heap, (0.0, self.handle_employee_available, 1))
        heapq.heappush(self.event_heap, (0.0, self.handle_employee_available, 2))
        heapq.heappush(self.event_heap, (0.0, self.generate_client))

    def log_event(self, event_type: str, entity_type: str, entity: str, payload: dict):
        """Emits a JSONL event if within simulation horizon."""
        if self.current_time <= self.sim_time:
            obj = {
                "time": self.current_time,
                "time_str": format_time(self.current_time),
                "event": event_type,
                "entity_type": entity_type,
                "entity": entity,
                "payload": payload
            }
            print(json.dumps(obj))

    def run(self):
        """Main simulation loop."""
        while self.event_heap:
            time, callback, args = heapq.heappop(self.event_heap)
            
            # Stop if we have passed the simulation horizon
            if time > self.sim_time:
                break
                
            self.current_time = time
            callback(*args)
            
            if not self.event_heap:
                break

    def handle_employee_available(self, employee_id: int):
        """Handles an employee becoming available."""
        emp_name = self.employees[employee_id]["name"]
        self.employees[employee_id]["available"] = True
        
        self.log_event("employee_available", "employee", emp_name, {"employee_id": employee_id})
        
        # Attempt to pair with a waiting client
        self.try_pair_client(employee_id)

    def generate_client(self):
        """Generates a new client and schedules the next one."""
        cid = self.client_id_counter
        self.client_id_counter += 1
        self.client_arrival_times[cid] = self.current_time
        
        self.log_event("client_generated", "client_generator", "ClientGenerator", 
                       {"client_id": cid, "arrival_time": self.current_time})
        
        self.waiting_queue.append(cid)
        
        # Try to pair immediately with any available employee
        self.try_pair_any()
        
        # Calculate next inter-arrival time
        # 0 <= interval <= client_mean + 5 * client_stddev
        mean = self.client_mean
        stddev = self.client_stddev
        
        interval = random.normalvariate(mean, stddev)
        max_interval = mean + 5 * stddev
        interval = max(0.0, min(interval, max_interval))
        
        next_time = self.current_time + interval
        heapq.heappush(self.event_heap, (next_time, self.generate_client))

    def try_pair_any(self):
        """Iterates through employees to find available ones for the queue."""
        for eid in [1, 2]:
            if self.employees[eid]["available"]:
                self.try_pair_client(eid)

    def try_pair_client(self, employee_id: int):
        """Pairs an available employee with the first client in the FIFO queue."""
        if not self.employees[employee_id]["available"]:
            return
        if not self.waiting_queue:
            return
            
        # FIFO pop
        client_id = self.waiting_queue.popleft()
        self.employees[employee_id]["available"] = False
        
        self.log_event("client_paired", "queue", "Queue", 
                       {"client_id": client_id, "employee_id": employee_id, "paired_time": self.current_time})
        
        # Calculate service duration
        # employee_mean - 3 * employee_stddev <= duration <= employee_mean + 3 * employee_stddev
        if employee_id == 1:
            mean = self.emp1_mean
            stddev = self.emp1_stddev
        else:
            mean = self.emp2_mean
            stddev = self.emp2_stddev
            
        if stddev == 0:
            duration = mean
        else:
            duration = random.normalvariate(mean, stddev)
            min_dur = mean - 3 * stddev
            max_dur = mean + 3 * stddev
            duration = max(min_dur, min(duration, max_dur))
            
        finish_time = self.current_time + duration
        heapq.heappush(self.event_heap, (finish_time, self.handle_client_served, client_id, employee_id))

    def handle_client_served(self, client_id: int, employee_id: int):
        """Handles service completion for a client."""
        emp_name = self.employees[employee_id]["name"]
        arrived = self.client_arrival_times.get(client_id, 0.0)
        delay = self.current_time - arrived
        
        self.log_event("client_served", "employee", emp_name,
                       {"client_id": client_id, "employee_id": employee_id, 
                        "arrived": arrived, "dispatched": self.current_time, "delay": delay})
        
        # Employee becomes available again
        self.handle_employee_available(employee_id)

def main():
    parser = argparse.ArgumentParser(description="Two-Employee Store Cashier Simulation")
    
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000",
                        help="Total simulation horizon in HH:MM:SS:mmm format")
    parser.add_argument("--client_mean", type=float, default=10.0)
    parser.add_argument("--client_stddev", type=float, default=5.0)
    parser.add_argument("--employee_1_mean", type=float, default=20.0)
    parser.add_argument("--employee_1_stddev", type=float, default=0.0)
    parser.add_argument("--employee_2_mean", type=float, default=30.0)
    parser.add_argument("--employee_2_stddev", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    
    args = parser.parse_args()
    
    sim = Simulation(args)
    sim.run()

if __name__ == "__main__":
    main()