import sys
import argparse
import json
import random
import math

# xdevs imports
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Constants
INFINITY = float('inf')

# Helper Functions
def format_time_str(seconds: float) -> str:
    """Converts simulation time in seconds to HH:MM:SS:mmm format."""
    h = int(seconds // 3600)
    rem = seconds % 3600
    m = int(rem // 60)
    rem = rem % 60
    s = int(rem // 1)
    ms = int(round((rem % 1) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"

def log_event(time: float, event_type: str, entity_type: str, entity: str, payload: dict):
    """Prints a JSONL event to stdout."""
    obj = {
        "time": time,
        "time_str": format_time_str(time),
        "event": event_type,
        "entity_type": entity_type,
        "entity": entity,
        "payload": payload
    }
    print(json.dumps(obj), file=sys.stdout, flush=True)

# Atomic Models

class ClientGenerator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, mean: float, stddev: float):
        super().__init__(name)
        self.parent = parent
        self.mean = mean
        self.stddev = stddev
        self.client_id = 1
        
        self.out_client = self.add_out_port(Port(object, "out_client"))

    def initialize(self):
        # First client at t=0.0
        self.hold_in("active", 0.0)

    def lambdaf(self):
        if self.phase == "active":
            payload = {
                "client_id": self.client_id,
                "arrival_time": self.time
            }
            self.out_client.add(payload)
            log_event(self.time, "client_generated", "client_generator", "ClientGenerator", payload)

    def deltint(self):
        if self.phase == "active":
            self.client_id += 1
            # Sample next interval
            val = random.gauss(self.mean, self.stddev)
            # Clamp: 0 <= interval <= mean + 5*stddev
            interval = max(0.0, min(val, self.mean + 5 * self.stddev))
            self.hold_in("active", interval)

    def deltext(self, e):
        pass

    def exit(self):
        pass

class Queue(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.in_client = self.add_in_port(Port(object, "in_client"))
        self.in_avail = self.add_in_port(Port(object, "in_avail"))
        self.out_pair = self.add_out_port(Port(object, "out_pair"))
        
        self.queue = [] # List of dicts: {client_id, arrival_time}
        self.available_employees = set() # Set of employee_ids
        self.pending_pairs = [] # List of dicts to output

    def initialize(self):
        self.hold_in("passive", INFINITY)

    def lambdaf(self):
        if self.phase == "pairing":
            for p in self.pending_pairs:
                self.out_pair.add(p)
                log_event(self.time, "client_paired", "queue", "Queue", {
                    "client_id": p["client_id"],
                    "employee_id": p["employee_id"],
                    "paired_time": self.time
                })

    def deltint(self):
        self.pending_pairs = []
        self.hold_in("passive", INFINITY)

    def deltext(self, e):
        # Process incoming clients
        for val in self.in_client.values:
            self.queue.append(val)
            
        # Process incoming availabilities
        for val in self.in_avail.values:
            self.available_employees.add(val["employee_id"])
            
        # Pair logic
        self.pending_pairs = []
        while self.queue and self.available_employees:
            client = self.queue.pop(0) # FIFO
            emp_id = self.available_employees.pop()
            
            self.pending_pairs.append({
                "client_id": client["client_id"],
                "employee_id": emp_id,
                "arrival_time": client["arrival_time"]
            })
            
        if self.pending_pairs:
            self.hold_in("pairing", 0.0)
        else:
            self.hold_in("passive", INFINITY)

    def exit(self):
        pass

class Employee(Atomic):
    def __init__(self, name: str, parent: Coupled | None, emp_id: int, mean: float, stddev: float):
        super().__init__(name)
        self.parent = parent
        self.emp_id = emp_id
        self.mean = mean
        self.stddev = stddev
        
        self.in_pair = self.add_in_port(Port(object, "in_pair"))
        self.out_served = self.add_out_port(Port(object, "out_served"))
        self.out_avail = self.add_out_port(Port(object, "out_avail"))
        
        self.current_client = None

    def initialize(self):
        self.hold_in("idle", 0.0)

    def lambdaf(self):
        if self.phase == "idle":
            self.out_avail.add({"employee_id": self.emp_id})
            log_event(self.time, "employee_available", "employee", f"Employee_{self.emp_id}", {"employee_id": self.emp_id})
        elif self.phase == "busy_done":
            arrived = self.current_client["arrival_time"]
            dispatched = self.time
            delay = dispatched - arrived
            
            payload = {
                "client_id": self.current_client["client_id"],
                "employee_id": self.emp_id,
                "arrived": arrived,
                "dispatched": dispatched,
                "delay": delay
            }
            self.out_served.add(payload)
            log_event(self.time, "client_served", "employee", f"Employee_{self.emp_id}", payload)

    def deltint(self):
        if self.phase == "idle":
            self.hold_in("passive", INFINITY)
        elif self.phase == "busy":
            self.hold_in("busy_done", 0.0)
        elif self.phase == "busy_done":
            self.current_client = None
            self.hold_in("idle", 0.0)

    def deltext(self, e):
        if self.phase in ["passive", "idle"]:
            for val in self.in_pair.values:
                if val["employee_id"] == self.emp_id:
                    self.current_client = val
                    # Sample duration
                    if self.stddev == 0:
                        duration = self.mean
                    else:
                        d_val = random.gauss(self.mean, self.stddev)
                        # Clamp: mean - 3*stddev <= duration <= mean + 3*stddev
                        duration = max(self.mean - 3*self.stddev, min(d_val, self.mean + 3*self.stddev))
                    
                    self.hold_in("busy", duration)
                    break

    def exit(self):
        pass

# Coupled Model

class StoreSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None, args):
        super().__init__(name)
        self.parent = parent
        
        # Instantiate components
        self.gen = ClientGenerator("ClientGenerator", self, args.client_mean, args.client_stddev)
        self.queue = Queue("Queue", self)
        self.emp1 = Employee("Employee_1", self, 1, args.employee_1_mean, args.employee_1_stddev)
        self.emp2 = Employee("Employee_2", self, 2, args.employee_2_mean, args.employee_2_stddev)
        
        self.add_component(self.gen)
        self.add_component(self.queue)
        self.add_component(self.emp1)
        self.add_component(self.emp2)
        
        # Define couplings
        # Generator -> Queue
        self.add_coupling(self.gen.out_client, self.queue.in_client)
        
        # Employees -> Queue (Availability)
        self.add_coupling(self.emp1.out_avail, self.queue.in_avail)
        self.add_coupling(self.emp2.out_avail, self.queue.in_avail)
        
        # Queue -> Employees (Pairing)
        # Queue broadcasts pair info, employees filter based on ID
        self.add_coupling(self.queue.out_pair, self.emp1.in_pair)
        self.add_coupling(self.queue.out_pair, self.emp2.in_pair)

# Main Entry Point

def parse_simulation_time(time_str: str) -> float:
    """Parses HH:MM:SS:mmm to seconds."""
    parts = time_str.split(':')
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {time_str}. Expected HH:MM:SS:mmm")
    
    h = int(parts[0])
    m = int(parts[1])
    s = int(parts[2])
    ms = int(parts[3])
    
    return h * 3600 + m * 60 + s + ms / 1000.0

def main():
    parser = argparse.ArgumentParser(description="Two-Employee Store Cashier Simulation")
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000", help="Simulation horizon in HH:MM:SS:mmm format")
    parser.add_argument("--client_mean", type=float, default=10.0)
    parser.add_argument("--client_stddev", type=float, default=5.0)
    parser.add_argument("--employee_1_mean", type=float, default=20.0)
    parser.add_argument("--employee_1_stddev", type=float, default=0.0)
    parser.add_argument("--employee_2_mean", type=float, default=30.0)
    parser.add_argument("--employee_2_stddev", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    
    args = parser.parse_args()
    
    if args.seed is not None:
        random.seed(args.seed)
    
    sim_time_seconds = parse_simulation_time(args.simulation_time)
    
    root = StoreSystem("StoreSystem", None, args)
    coord = Coordinator(root, clock=SimulationClock(0))
    
    coord.initialize()
    coord.simulate_time(sim_time_seconds)

if __name__ == "__main__":
    main()