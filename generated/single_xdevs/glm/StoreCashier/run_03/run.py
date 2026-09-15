import sys
import json
import argparse
import random
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# --- Helper Functions ---

def format_time_str(time_val: float) -> str:
    """Converts simulation time (seconds) to HH:MM:SS:mmm string."""
    total_ms = int(time_val * 1000)
    ms = total_ms % 1000
    total_seconds = total_ms // 1000
    sec = total_seconds % 60
    total_minutes = total_seconds // 60
    min = total_minutes % 60
    hour = total_minutes // 60
    return f"{hour:02d}:{min:02d}:{sec:02d}:{ms:03d}"

def parse_time_str(time_str: str) -> float:
    """Converts HH:MM:SS:mmm string to simulation time (seconds)."""
    parts = time_str.split(':')
    h = int(parts[0])
    m = int(parts[1])
    s = int(parts[2])
    ms = int(parts[3])
    return (h * 3600) + (m * 60) + s + (ms / 1000.0)

def log_event(time: float, event_type: str, entity_type: str, entity: str, payload: dict):
    """Prints a JSONL event to stdout."""
    entry = {
        "time": time,
        "time_str": format_time_str(time),
        "event": event_type,
        "entity_type": entity_type,
        "entity": entity,
        "payload": payload
    }
    print(json.dumps(entry), file=sys.stdout, flush=True)

# --- Atomic Models ---

class ClientGenerator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, mean: float, stddev: float, seed: int):
        super().__init__(name)
        self.parent = parent
        
        self.mean = mean
        self.stddev = stddev
        self.rng = random.Random(seed)
        self.client_id_counter = 0
        
        self.out_generate = Port(object, "out_generate")
        self.add_out_port(self.out_generate)
        
        self.hold_in("IDLE", float('inf'))

    def initialize(self):
        # First client at t=0.0
        self.client_id_counter += 1
        self.hold_in("GENERATING", 0.0)

    def lambdaf(self):
        if self.phase == "GENERATING":
            self.out_generate.add({
                "client_id": self.client_id_counter,
                "arrival_time": self.clock.get_time()
            })

    def deltint(self):
        # Schedule next client
        self.client_id_counter += 1
        
        # Sample inter-arrival time: 0 <= interval <= mean + 5*stddev
        interval = self.rng.gauss(self.mean, self.stddev)
        upper_bound = self.mean + 5 * self.stddev
        interval = max(0.0, min(interval, upper_bound))
        
        self.hold_in("GENERATING", interval)

    def deltext(self, e):
        pass

    def exit(self):
        pass


class Queue(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.in_arrive = Port(object, "in_arrive")
        self.in_available = Port(object, "in_available")
        self.out_paired = Port(object, "out_paired")
        
        self.add_in_port(self.in_arrive)
        self.add_in_port(self.in_available)
        self.add_out_port(self.out_paired)
        
        # State
        self.queue = []  # List of client dicts
        self.available_employees = [] # List of employee IDs
        self.pending_pairs = [] # List of pair payloads to output
        
        self.hold_in("PASSIVE", float('inf'))

    def initialize(self):
        self.hold_in("PASSIVE", float('inf'))

    def lambdaf(self):
        if self.phase == "PAIRING":
            for p in self.pending_pairs:
                self.out_paired.add(p)

    def deltint(self):
        self.pending_pairs = []
        self.hold_in("PASSIVE", float('inf'))

    def deltext(self, e):
        # Process arrivals
        for val in self.in_arrive.values:
            self.queue.append(val)
            
        # Process availabilities
        for val in self.in_available.values:
            eid = val["employee_id"]
            if eid not in self.available_employees:
                self.available_employees.append(eid)
        
        # Pair clients and employees
        while self.queue and self.available_employees:
            client = self.queue.pop(0) # FIFO
            eid = self.available_employees.pop(0)
            
            self.pending_pairs.append({
                "client_id": client["client_id"],
                "employee_id": eid,
                "paired_time": self.clock.get_time(),
                "arrival_time": client["arrival_time"]
            })
        
        if self.pending_pairs:
            self.hold_in("PAIRING", 0.0)
        else:
            self.hold_in("PASSIVE", float('inf'))

    def exit(self):
        pass


class Employee(Atomic):
    def __init__(self, name: str, parent: Coupled | None, emp_id: int, mean: float, stddev: float, seed: int):
        super().__init__(name)
        self.parent = parent
        
        self.emp_id = emp_id
        self.mean = mean
        self.stddev = stddev
        self.rng = random.Random(seed + emp_id)
        
        self.in_paired = Port(object, "in_paired")
        self.out_served = Port(object, "out_served")
        self.out_available = Port(object, "out_available")
        
        self.add_in_port(self.in_paired)
        self.add_out_port(self.out_served)
        self.add_out_port(self.out_available)
        
        self.current_client = None
        self.arrival_time = 0.0
        
        self.hold_in("IDLE", 0.0)

    def initialize(self):
        self.hold_in("IDLE", 0.0)

    def lambdaf(self):
        if self.phase == "IDLE":
            self.out_available.add({"employee_id": self.emp_id})
        elif self.phase == "SERVING":
            self.out_served.add({
                "client_id": self.current_client,
                "employee_id": self.emp_id,
                "arrived": self.arrival_time,
                "dispatched": self.clock.get_time(),
                "delay": self.clock.get_time() - self.arrival_time
            })

    def deltint(self):
        if self.phase == "IDLE":
            self.hold_in("WAITING", float('inf'))
        elif self.phase == "SERVING":
            self.current_client = None
            self.hold_in("IDLE", 0.0)

    def deltext(self, e):
        if self.phase == "WAITING":
            for val in self.in_paired.values:
                self.current_client = val["client_id"]
                self.arrival_time = val["arrival_time"]
                
                # Sample service duration: mean - 3*stddev <= dur <= mean + 3*stddev
                duration = self.rng.gauss(self.mean, self.stddev)
                lower_bound = self.mean - 3 * self.stddev
                upper_bound = self.mean + 3 * self.stddev
                duration = max(lower_bound, min(duration, upper_bound))
                
                self.hold_in("SERVING", duration)
                return

    def exit(self):
        pass


class Logger(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.in_gen = Port(object, "in_gen")
        self.in_pair = Port(object, "in_pair")
        self.in_served = Port(object, "in_served")
        self.in_avail = Port(object, "in_avail")
        
        self.add_in_port(self.in_gen)
        self.add_in_port(self.in_pair)
        self.add_in_port(self.in_served)
        self.add_in_port(self.in_avail)
        
        self.hold_in("PASSIVE", float('inf'))

    def initialize(self):
        self.hold_in("PASSIVE", float('inf'))

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("PASSIVE", float('inf'))

    def deltext(self, e):
        t = self.clock.get_time()
        
        for val in self.in_gen.values:
            log_event(t, "client_generated", "client_generator", "ClientGenerator", val)
            
        for val in self.in_avail.values:
            log_event(t, "employee_available", "employee", f"Employee_{val['employee_id']}", val)
            
        for val in self.in_pair.values:
            log_event(t, "client_paired", "queue", "Queue", val)
            
        for val in self.in_served.values:
            log_event(t, "client_served", "employee", f"Employee_{val['employee_id']}", val)
            
        self.hold_in("PASSIVE", float('inf'))

    def exit(self):
        pass


# --- Coupled Model ---

class StoreSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None, args):
        super().__init__(name)
        self.parent = parent
        
        seed = args.seed if args.seed else 42
        
        # Components
        self.generator = ClientGenerator("ClientGenerator", self, args.client_mean, args.client_stddev, seed)
        self.add_component(self.generator)
        
        self.queue = Queue("Queue", self)
        self.add_component(self.queue)
        
        self.emp1 = Employee("Employee_1", self, 1, args.employee_1_mean, args.employee_1_stddev, seed)
        self.add_component(self.emp1)
        
        self.emp2 = Employee("Employee_2", self, 2, args.employee_2_mean, args.employee_2_stddev, seed)
        self.add_component(self.emp2)
        
        self.logger = Logger("Logger", self)
        self.add_component(self.logger)
        
        # Internal Couplings
        self.add_coupling(self.generator.out_generate, self.queue.in_arrive)
        self.add_coupling(self.queue.out_paired, self.emp1.in_paired)
        self.add_coupling(self.queue.out_paired, self.emp2.in_paired)
        self.add_coupling(self.emp1.out_available, self.queue.in_available)
        self.add_coupling(self.emp2.out_available, self.queue.in_available)
        
        # Logger Couplings
        self.add_coupling(self.generator.out_generate, self.logger.in_gen)
        self.add_coupling(self.queue.out_paired, self.logger.in_pair)
        self.add_coupling(self.emp1.out_served, self.logger.in_served)
        self.add_coupling(self.emp2.out_served, self.logger.in_served)
        self.add_coupling(self.emp1.out_available, self.logger.in_avail)
        self.add_coupling(self.emp2.out_available, self.logger.in_avail)


# --- Main Entry Point ---

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000")
    parser.add_argument("--client_mean", type=float, default=10.0)
    parser.add_argument("--client_stddev", type=float, default=5.0)
    parser.add_argument("--employee_1_mean", type=float, default=20.0)
    parser.add_argument("--employee_1_stddev", type=float, default=0.0)
    parser.add_argument("--employee_2_mean", type=float, default=30.0)
    parser.add_argument("--employee_2_stddev", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=None)
    
    args = parser.parse_args()
    
    root = StoreSystem("StoreSystem", None, args)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    
    duration = parse_time_str(args.simulation_time)
    coord.simulate_time(duration)

if __name__ == "__main__":
    main()