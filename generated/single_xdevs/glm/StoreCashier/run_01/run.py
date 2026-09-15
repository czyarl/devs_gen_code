import sys
import argparse
import json
import random
import math
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# --- Helper Functions ---

def format_time_str(seconds: float) -> str:
    """Converts simulation seconds to HH:MM:SS:mmm format."""
    total_ms = int(seconds * 1000)
    ms = total_ms % 1000
    total_seconds = total_ms // 1000
    s = total_seconds % 60
    total_minutes = total_seconds // 60
    m = total_minutes % 60
    h = total_minutes // 60
    return f"{h:02d}:{m:02d}:{s:02d}:{ms:03d}"

def parse_time_str(time_str: str) -> float:
    """Converts HH:MM:SS:mmm format to simulation seconds."""
    parts = time_str.split(':')
    if len(parts) != 4:
        raise ValueError("Invalid time format. Expected HH:MM:SS:mmm")
    h, m, s, ms = map(int, parts)
    return h * 3600 + m * 60 + s + ms / 1000.0

def log_event(time: float, event: str, entity_type: str, entity: str, payload: dict):
    """Prints a JSONL event to stdout."""
    output = {
        "time": time,
        "time_str": format_time_str(time),
        "event": event,
        "entity_type": entity_type,
        "entity": entity,
        "payload": payload
    }
    print(json.dumps(output), file=sys.stdout, flush=True)

# --- Atomic Models ---

class ClientGenerator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, mean: float, stddev: float, seed: int | None):
        super().__init__(name, parent)
        self.mean = mean
        self.stddev = stddev
        self.rng = random.Random(seed)
        
        self.client_id_counter = 1
        
        self.out_generate = Port(object, "out_generate")
        self.add_out_port(self.out_generate)
        
        self.hold_in("active", 0.0)

    def initialize(self):
        # First client at t=0.0
        self.hold_in("active", 0.0)

    def lambdaf(self):
        # Output the generated client info
        payload = {
            "client_id": self.client_id_counter,
            "arrival_time": self.time
        }
        self.out_generate.add(payload)
        
        # Log event
        log_event(self.time, "client_generated", "client_generator", "ClientGenerator", payload)

    def deltint(self):
        # Schedule next generation
        self.client_id_counter += 1
        
        interval = 0.0
        if self.stddev > 0:
            # Sample from normal distribution, but clamp to [0, mean + 5*stddev]
            val = self.rng.gauss(self.mean, self.stddev)
            max_val = self.mean + 5 * self.stddev
            interval = max(0.0, min(val, max_val))
        else:
            interval = self.mean
            
        self.hold_in("active", interval)

    def deltext(self, e):
        # No external inputs expected for generator
        pass

    def exit(self):
        pass

class Employee(Atomic):
    def __init__(self, name: str, parent: Coupled | None, emp_id: int, mean: float, stddev: float, seed: int | None):
        super().__init__(name, parent)
        self.emp_id = emp_id
        self.mean = mean
        self.stddev = stddev
        self.rng = random.Random(seed)
        
        self.in_assign = Port(object, "in_assign")
        self.add_in_port(self.in_assign)
        
        self.out_done = Port(object, "out_done")
        self.add_out_port(self.out_done)
        
        self.out_available = Port(object, "out_available")
        self.add_out_port(self.out_available)
        
        # State
        self.current_client = None # dict with client_id, arrived
        self.paired_time = 0.0
        
        self.hold_in("idle", 0.0)

    def initialize(self):
        # Initially available
        self.hold_in("idle", 0.0)

    def lambdaf(self):
        if self.phase == "idle":
            # Emit availability signal
            payload = {"employee_id": self.emp_id}
            self.out_available.add(payload)
            log_event(self.time, "employee_available", "employee", f"Employee_{self.emp_id}", payload)
            
        elif self.phase == "busy":
            # Emit service completion
            if self.current_client:
                payload = {
                    "client_id": self.current_client["client_id"],
                    "employee_id": self.emp_id,
                    "arrived": self.current_client["arrival_time"],
                    "dispatched": self.time,
                    "delay": self.time - self.current_client["arrival_time"]
                }
                self.out_done.add(payload)
                log_event(self.time, "client_served", "employee", f"Employee_{self.emp_id}", payload)

    def deltint(self):
        if self.phase == "idle":
            # After announcing availability, stay idle indefinitely until input
            self.hold_in("idle", float('inf'))
        elif self.phase == "busy":
            # Service finished
            self.current_client = None
            self.paired_time = 0.0
            self.hold_in("idle", 0.0)

    def deltext(self, e):
        # If idle and receive assignment, start working
        if self.phase == "idle" and not self.in_assign.is_empty():
            for job in self.in_assign.values:
                if job["employee_id"] == self.emp_id:
                    self.current_client = job
                    self.paired_time = self.time
                    
                    duration = 0.0
                    if self.stddev > 0:
                        # Sample from normal, clamp to [mean - 3*stddev, mean + 3*stddev]
                        val = self.rng.gauss(self.mean, self.stddev)
                        min_val = self.mean - 3 * self.stddev
                        max_val = self.mean + 3 * self.stddev
                        duration = max(min_val, min(val, max_val))
                    else:
                        duration = self.mean
                    
                    self.hold_in("busy", duration)
                    break # Only handle one job per transition (though shouldn't get multiple)

    def exit(self):
        pass

class Queue(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name, parent)
        
        self.in_generated = Port(object, "in_generated")
        self.add_in_port(self.in_generated)
        
        self.in_done = Port(object, "in_done")
        self.add_in_port(self.in_done)
        
        self.in_available = Port(object, "in_available")
        self.add_in_port(self.in_available)
        
        self.out_assign = Port(object, "out_assign")
        self.add_out_port(self.out_assign)
        
        # State
        self.waiting_queue = [] # list of client dicts
        self.available_employees = set() # set of employee IDs
        
        self.hold_in("passive", float('inf'))

    def initialize(self):
        self.hold_in("passive", float('inf'))

    def lambdaf(self):
        # Send assignments
        # We can assign multiple clients if multiple employees available
        while self.waiting_queue and self.available_employees:
            client = self.waiting_queue.pop(0)
            emp_id = self.available_employees.pop() # FIFO for employees too? Or any? "paired immediately when both... exist"
            
            payload = {
                "client_id": client["client_id"],
                "employee_id": emp_id,
                "paired_time": self.time
            }
            self.out_assign.add(payload)
            
            # Log pairing
            log_event(self.time, "client_paired", "queue", "Queue", payload)

    def deltint(self):
        # Internal transitions only happen if we output assignments.
        # After outputting, we might still have clients or employees.
        # If we have both, we should output immediately again (sigma=0).
        # If not, go passive.
        
        if self.waiting_queue and self.available_employees:
            self.hold_in("assigning", 0.0)
        else:
            self.hold_in("passive", float('inf'))

    def deltext(self, e):
        # Process inputs
        # 1. New clients
        if not self.in_generated.is_empty():
            for client in self.in_generated.values:
                self.waiting_queue.append(client)
        
        # 2. Service completions (Employee becomes available)
        # Note: The Employee model handles the availability signal emission logic separately.
        # But here we might receive 'done' signals. However, the Employee model emits 'available' separately.
        # We only care about 'available' signals to know who is free.
        if not self.in_available.is_empty():
            for avail in self.in_available.values:
                self.available_employees.add(avail["employee_id"])
        
        # 3. Done signals (optional, but we might not need them if availability is handled separately)
        # The spec says: "employee_available is emitted when an employee is idle... including initial availability and after service completion."
        # So we rely on in_available.
        
        # Determine next phase
        if self.waiting_queue and self.available_employees:
            self.hold_in("assigning", 0.0)
        else:
            self.hold_in("passive", float('inf'))

    def exit(self):
        pass

# --- Coupled Model ---

class StoreSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None, config: dict):
        super().__init__(name, parent)
        
        # Config
        sim_time = config.get("simulation_time", 300.0)
        seed = config.get("seed", None)
        
        # Components
        self.generator = ClientGenerator(
            name="Generator", 
            parent=self, 
            mean=config["client_mean"],
            stddev=config["client_stddev"],
            seed=seed
        )
        self.add_component(self.generator)
        
        self.queue = Queue(name="Queue", parent=self)
        self.add_component(self.queue)
        
        self.employee1 = Employee(
            name="Employee1", 
            parent=self, 
            emp_id=1,
            mean=config["emp1_mean"],
            stddev=config["emp1_stddev"],
            seed=seed
        )
        self.add_component(self.employee1)
        
        self.employee2 = Employee(
            name="Employee2", 
            parent=self, 
            emp_id=2,
            mean=config["emp2_mean"],
            stddev=config["emp2_stddev"],
            seed=seed
        )
        self.add_component(self.employee2)
        
        # Couplings
        
        # Generator -> Queue
        self.add_coupling(self.generator.out_generate, self.queue.in_generated)
        
        # Queue -> Employees (Assignment)
        self.add_coupling(self.queue.out_assign, self.employee1.in_assign)
        self.add_coupling(self.queue.out_assign, self.employee2.in_assign)
        
        # Employees -> Queue (Availability)
        self.add_coupling(self.employee1.out_available, self.queue.in_available)
        self.add_coupling(self.employee2.out_available, self.queue.in_available)
        
        # Employees -> (External/Logging) - Done events are logged inside Employee.lambdaf
        # But we need to ensure the simulation doesn't crash if ports are unused.
        # The Employee model logs directly. We don't need to couple 'out_done' to anything 
        # unless we needed to process it elsewhere. The spec says "client_served" is an event.
        # Since we log inside lambdaf, we don't strictly need to couple this out port for data flow,
        # but it's good practice to have it if we were using a Logger component.
        # Here, we rely on Atomic models logging their own events to stdout as requested.
        
# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Two-Employee Store Cashier Simulation")
    
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000", 
                        help="Total simulation horizon in HH:MM:SS:mmm format")
    
    # Benchmark defaults
    parser.add_argument("--client_mean", type=float, default=10.0)
    parser.add_argument("--client_stddev", type=float, default=5.0)
    parser.add_argument("--employee_1_mean", type=float, default=20.0)
    parser.add_argument("--employee_1_stddev", type=float, default=0.0)
    parser.add_argument("--employee_2_mean", type=float, default=30.0)
    parser.add_argument("--employee_2_stddev", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility")
    
    args = parser.parse_args()
    
    try:
        horizon_seconds = parse_time_str(args.simulation_time)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
        
    config = {
        "simulation_time": horizon_seconds,
        "client_mean": args.client_mean,
        "client_stddev": args.client_stddev,
        "emp1_mean": args.employee_1_mean,
        "emp1_stddev": args.employee_1_stddev,
        "emp2_mean": args.employee_2_mean,
        "emp2_stddev": args.employee_2_stddev,
        "seed": args.seed
    }
    
    root = StoreSystem(name="StoreSystem", parent=None, config=config)
    
    # xdevs Coordinator
    # SimulationClock(0) starts at t=0
    coord = Coordinator(root, clock=SimulationClock(0))
    
    coord.initialize()
    
    # simulate_time runs until the specified time
    coord.simulate_time(horizon_seconds)

if __name__ == "__main__":
    main()