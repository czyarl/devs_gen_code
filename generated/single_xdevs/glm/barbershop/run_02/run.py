import sys
import json
import argparse
import logging
import time
from collections import deque

# xdevs imports
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Setup logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# Helper for output
def print_json(record):
    print(json.dumps(record), file=sys.stdout, flush=True)

# --- Atomic Models ---

class Reception(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.in_newcust = Port(object, "in_newcust")
        self.in_done = Port(object, "in_done")
        self.out_cust = Port(object, "cust")
        
        self.add_in_port(self.in_newcust)
        self.add_in_port(self.in_done)
        self.add_out_port(self.out_cust)
        
        # State
        self.queue = deque()
        self.max_capacity = 8
        self.checkhair_free = True
        
        # Phases: "idle", "processing", "blocked", "sending"
        self.phase = "idle"
        self.sigma = float('inf')

    def initialize(self):
        self.hold_in("idle", float('inf'))
        self.log_state("total customers num", 0)

    def deltext(self, e):
        if self.phase == "processing":
            self.sigma -= e
        
        # Handle new customer arrivals
        if self.in_newcust.values:
            for _ in self.in_newcust.values:
                if len(self.queue) < self.max_capacity:
                    self.queue.append("newcust")
                    self.log_state("total customers num", len(self.queue))
                    if self.phase == "idle":
                        self.hold_in("processing", 5.0)
        
        # Handle done signal from Checkhair
        if self.in_done.values:
            self.checkhair_free = True
            if self.phase == "blocked":
                if self.queue:
                    self.queue.popleft()
                    self.log_state("total customers num", len(self.queue))
                    self.hold_in("sending", 0.0)
                else:
                    self.hold_in("idle", float('inf'))
        
        # Maintain state if no explicit transition triggered above
        if self.phase == "idle":
            self.hold_in("idle", float('inf'))
        elif self.phase == "processing":
            self.hold_in("processing", self.sigma)
        elif self.phase == "blocked":
            self.hold_in("blocked", float('inf'))

    def deltint(self):
        if self.phase == "processing":
            # 5 seconds finished
            if self.checkhair_free:
                if self.queue:
                    self.queue.popleft()
                    self.log_state("total customers num", len(self.queue))
                    self.hold_in("sending", 0.0)
                    return
            self.hold_in("blocked", float('inf'))
            
        elif self.phase == "sending":
            self.checkhair_free = False
            if self.queue:
                self.hold_in("processing", 5.0)
            else:
                self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "sending":
            self.out_cust.add("newcust")
            print_json({
                "time": self.clock.get_time(),
                "type": "message",
                "model": "reception",
                "port": "cust",
                "content": "newcust"
            })

    def exit(self):
        pass

    def log_state(self, field, value):
        print_json({
            "time": self.clock.get_time(),
            "type": "state",
            "model": "reception",
            "field": field,
            "value": value
        })


class Checkhair(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.in_cust = Port(object, "cust")
        self.in_done_cut = Port(object, "done_cut")
        self.out_cut = Port(object, "to_cut")
        self.out_reception = Port(object, "to_reception")
        
        self.add_in_port(self.in_cust)
        self.add_in_port(self.in_done_cut)
        self.add_out_port(self.out_cut)
        self.add_out_port(self.out_reception)
        
        # Phases
        self.phase = "available"
        self.sigma = float('inf')
        
        self.current_customer = None

    def initialize(self):
        self.hold_in("available", float('inf'))
        self.log_state("customer", "done")

    def deltext(self, e):
        if self.phase == "inspecting":
            self.sigma -= e
            
        if self.in_cust.values and self.phase == "available":
            self.current_customer = "newcust"
            self.log_state("customer", "newcust")
            self.hold_in("inspecting", 7.0)
            return

        if self.in_done_cut.values and self.phase == "waiting_cut":
            self.hold_in("finishing", 0.0)
            return

    def deltint(self):
        if self.phase == "inspecting":
            self.hold_in("waiting_cut", float('inf'))
        elif self.phase == "finishing":
            self.current_customer = None
            self.log_state("customer", "done")
            self.hold_in("available", float('inf'))

    def lambdaf(self):
        if self.phase == "inspecting":
            self.out_cut.add("newcust")
            print_json({
                "time": self.clock.get_time(),
                "type": "message",
                "model": "checkhair",
                "port": "to_cut",
                "content": "newcust"
            })
        elif self.phase == "finishing":
            self.out_reception.add("done")
            print_json({
                "time": self.clock.get_time(),
                "type": "message",
                "model": "checkhair",
                "port": "to_reception",
                "content": "done"
            })

    def exit(self):
        pass

    def log_state(self, field, value):
        print_json({
            "time": self.clock.get_time(),
            "type": "state",
            "model": "checkhair",
            "field": field,
            "value": value
        })


class Cuthair(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.in_cust = Port(object, "cust")
        self.out_done = Port(object, "out")
        
        self.add_in_port(self.in_cust)
        self.add_out_port(self.out_done)
        
        # Phases
        self.phase = "idle"
        self.sigma = float('inf')
        
        self.total_customer_done = 0

    def initialize(self):
        self.hold_in("idle", float('inf'))
        self.log_state("total customer done", 0)

    def deltext(self, e):
        if self.phase == "cutting":
            self.sigma -= e
        if self.in_cust.values and self.phase == "idle":
            self.hold_in("cutting", 20.0)

    def deltint(self):
        if self.phase == "cutting":
            self.total_customer_done += 1
            self.log_state("total customer done", self.total_customer_done)
            self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "cutting":
            self.out_done.add("done")
            print_json({
                "time": self.clock.get_time(),
                "type": "message",
                "model": "cuthair",
                "port": "out",
                "content": "done"
            })

    def exit(self):
        pass

    def log_state(self, field, value):
        print_json({
            "time": self.clock.get_time(),
            "type": "state",
            "model": "cuthair",
            "field": field,
            "value": value
        })


class InputGenerator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, schedule: list):
        super().__init__(name)
        self.parent = parent
        self.schedule = sorted(schedule, key=lambda x: x[0])
        
        self.out_cust = Port(object, "newcust")
        self.add_out_port(self.out_cust)
        
        self.phase = "active"
        self.sigma = self.schedule[0][0] if self.schedule else float('inf')

    def initialize(self):
        self.hold_in("active", self.sigma)

    def deltint(self):
        current_time = self.clock.get_time()
        # Remove processed events (those <= current time)
        # Lambdaf handles outputting them, deltint handles cleanup
        while self.schedule and self.schedule[0][0] <= current_time + 1e-9:
            self.schedule.pop(0)
            
        if self.schedule:
            next_time = self.schedule[0][0]
            self.hold_in("active", next_time - current_time)
        else:
            self.hold_in("finished", float('inf'))

    def lambdaf(self):
        if self.phase == "active":
            current_time = self.clock.get_time()
            # Output all events scheduled for this exact time
            while self.schedule and abs(self.schedule[0][0] - current_time) < 1e-9:
                _, event = self.schedule.pop(0)
                self.out_cust.add(event)

    def deltext(self, e):
        pass

    def exit(self):
        pass


# --- Coupled Model ---

class BarbershopSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None, schedule: list):
        super().__init__(name)
        self.parent = parent
        
        self.generator = InputGenerator("generator", self, schedule)
        self.reception = Reception("reception", self)
        self.checkhair = Checkhair("checkhair", self)
        self.cuthair = Cuthair("cuthair", self)
        
        self.add_component(self.generator)
        self.add_component(self.reception)
        self.add_component(self.checkhair)
        self.add_component(self.cuthair)
        
        self.add_coupling(self.generator.out_cust, self.reception.in_newcust)
        self.add_coupling(self.reception.out_cust, self.checkhair.in_cust)
        self.add_coupling(self.checkhair.out_reception, self.reception.in_done)
        self.add_coupling(self.checkhair.out_cut, self.cuthair.in_cust)
        self.add_coupling(self.cuthair.out_done, self.checkhair.in_done_cut)


# --- Main ---

def parse_time(time_str):
    parts = list(map(int, time_str.split(':')))
    h, m, s = parts[0], parts[1], parts[2]
    ms = parts[3] if len(parts) > 3 else 0
    return h * 3600 + m * 60 + s + ms / 1000.0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    schedule = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            time_str, event = line.split()
            t = parse_time(time_str)
            if event == "newcust":
                schedule.append((t, event))
        except ValueError:
            logger.warning(f"Skipping invalid line: {line}")

    root = BarbershopSystem("barbershop", None, schedule)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    
    start_real = time.time()
    coord.simulate_time(args.simulation_time)
    end_real = time.time()
    
    logger.info(f"Simulation finished in {end_real - start_real:.2f} real seconds.")

if __name__ == "__main__":
    main()