import sys
import argparse
import json
import logging
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Setup Logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Helper Functions for Output ---

def print_state(time: float, model: str, field: str, value):
    """Helper to print state changes to stdout as JSONL."""
    # Ensure value is JSON serializable (string or number)
    payload = {
        "time": time,
        "type": "state",
        "model": model,
        "field": field,
        "value": value
    }
    print(json.dumps(payload), file=sys.stdout, flush=True)

def print_message(time: float, model: str, port: str, content: str):
    """Helper to print communication events to stdout as JSONL."""
    payload = {
        "time": time,
        "type": "message",
        "model": model,
        "port": port,
        "content": content
    }
    print(json.dumps(payload), file=sys.stdout, flush=True)

# --- Atomic Models ---

class Reception(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.in_newcust = Port(object, "in_newcust")
        self.in_done = Port(object, "in_done") # From checkhair
        self.out_cust = Port(object, "out_cust")
        
        self.add_in_port(self.in_newcust)
        self.add_in_port(self.in_done)
        self.add_out_port(self.out_cust)
        
        # State
        self.queue = [] # List of customers waiting
        self.capacity = 8
        self.current_processing = None # The customer currently being processed (check-in)
        
        # Initial event schedule
        self.hold_in("idle", float('inf'))

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def deltint(self):
        # Internal transition: Check-in time (5s) is over.
        # Move to ready state to output.
        if self.phase == "processing":
            self.hold_in("ready", 0)
            
        elif self.phase == "ready":
            # We just outputted (lambdaf called before deltint).
            # Now remove customer from internal tracking and check next.
            if self.current_processing:
                self.current_processing = None
                
            if self.queue:
                # Start processing next
                self.current_processing = self.queue.pop(0)
                self.hold_in("processing", 5.0)
            else:
                self.hold_in("idle", float('inf'))
        
        # Update state output
        total_customers = len(self.queue) + (1 if self.current_processing else 0)
        print_state(self.clock.get_time(), "reception", "total customers num", total_customers)

    def deltext(self, e):
        # External transition
        # Process inputs
        for port in [self.in_newcust, self.in_done]:
            for val in port.values:
                if port == self.in_newcust:
                    # New customer arrival
                    total = len(self.queue) + (1 if self.current_processing else 0)
                    if total < self.capacity:
                        self.queue.append("newcust")
                        logger.info(f"Reception: Customer accepted. Total: {total + 1}")
                    else:
                        logger.info(f"Reception: Customer rejected. Queue full.")
                
                elif port == self.in_done:
                    # Service complete notification from Checkhair
                    logger.info(f"Reception: Received service completion signal.")
        
        # State transition logic based on current phase
        if self.phase == "idle":
            if self.queue:
                # If we were idle and have customers, start processing
                self.current_processing = self.queue.pop(0)
                self.hold_in("processing", 5.0)
            else:
                self.hold_in("idle", float('inf'))
        elif self.phase == "processing":
            # If we are processing, we just update the queue (if new arrivals).
            # We don't interrupt the 5s processing.
            self.hold_in("processing", self.sigma - e)
        elif self.phase == "ready":
            # If we are ready to send, we hold until we can send (which is immediate in next lambda)
            self.hold_in("ready", self.sigma - e)
            
        # Update state output
        total_customers = len(self.queue) + (1 if self.current_processing else 0)
        print_state(self.clock.get_time(), "reception", "total customers num", total_customers)

    def lambdaf(self):
        # Output function
        if self.phase == "ready" and self.current_processing:
            # Send the customer to Checkhair
            self.out_cust.add("newcust")
            print_message(self.clock.get_time(), "reception", "cust", "newcust")

    def exit(self):
        pass


class Checkhair(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.in_cust = Port(object, "in_cust")
        self.in_cut_done = Port(object, "in_cut_done") # From Cuthair
        self.out_to_cut = Port(object, "out_to_cut")
        self.out_to_reception = Port(object, "out_to_reception")
        
        self.add_in_port(self.in_cust)
        self.add_in_port(self.in_cut_done)
        self.add_out_port(self.out_to_cut)
        self.add_out_port(self.out_to_reception)
        
        # State
        self.current_customer = None
        
        self.hold_in("available", float('inf'))

    def initialize(self):
        self.hold_in("available", float('inf'))

    def deltint(self):
        # Internal transition
        if self.phase == "consulting":
            # Consultation done. Send to cut.
            self.hold_in("waiting_cut_done", float('inf'))
            
        elif self.phase == "waiting_cut_done":
            # Waiting for external input
            self.hold_in("waiting_cut_done", float('inf'))
            
        elif self.phase == "notifying_reception":
            # Notification sent. Become available.
            self.current_customer = None
            self.hold_in("available", float('inf'))

    def deltext(self, e):
        # External transition
        has_input = False
        
        # Check inputs
        for val in self.in_cust.values:
            if self.phase == "available":
                # Receive customer
                self.current_customer = "newcust"
                self.hold_in("consulting", 7.0)
                has_input = True
                print_state(self.clock.get_time(), "checkhair", "customer", "newcust")
        
        for val in self.in_cut_done.values:
            if self.phase == "waiting_cut_done":
                # Cut is done. Notify reception.
                self.hold_in("notifying_reception", 0)
                has_input = True
                print_state(self.clock.get_time(), "checkhair", "customer", "done")
        
        if not has_input:
            # Resume current phase if no inputs processed
            self.hold_in(self.phase, self.sigma - e)

    def lambdaf(self):
        # Output
        if self.phase == "consulting":
            # Send to cut
            self.out_to_cut.add("newcust")
            print_message(self.clock.get_time(), "checkhair", "to_cut", "newcust")
            
        elif self.phase == "notifying_reception":
            # Send to reception
            self.out_to_reception.add("done")
            print_message(self.clock.get_time(), "checkhair", "to_reception", "done")

    def exit(self):
        pass


class Cuthair(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.in_cust = Port(object, "in_cust")
        self.out_done = Port(object, "out_done")
        
        self.add_in_port(self.in_cust)
        self.add_out_port(self.out_done)
        
        # State
        self.total_done = 0
        
        self.hold_in("idle", float('inf'))

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def deltint(self):
        # Internal transition
        if self.phase == "cutting":
            self.total_done += 1
            # We need to output "done" immediately
            self.hold_in("signaling", 0)
            
        elif self.phase == "signaling":
            # Done signaling, go back to idle
            self.hold_in("idle", float('inf'))

    def deltext(self, e):
        # External transition
        for val in self.in_cust.values:
            if self.phase == "idle":
                self.hold_in("cutting", 20.0)
                return
        
        # If no input or busy, resume
        self.hold_in(self.phase, self.sigma - e)

    def lambdaf(self):
        # Output
        if self.phase == "signaling":
            self.out_done.add("done")
            print_message(self.clock.get_time(), "cuthair", "out", "done")

    def exit(self):
        pass


class Generator(Atomic):
    """Reads schedule from stdin and injects events."""
    def __init__(self, name: str, parent: Coupled | None, schedule: list):
        super().__init__(name)
        self.parent = parent
        self.schedule = schedule # List of (time, event_name)
        self.schedule.sort(key=lambda x: x[0]) # Ensure sorted
        
        self.out_cust = Port(object, "out_cust")
        self.add_out_port(self.out_cust)
        
        self.current_index = 0
        self.hold_in("active", float('inf'))

    def initialize(self):
        if self.schedule:
            next_time = self.schedule[0][0]
            self.hold_in("active", next_time)
        else:
            self.hold_in("passive", float('inf'))

    def deltint(self):
        if self.phase == "active":
            # Processed the event at current time (which was output in lambdaf)
            self.current_index += 1
            
            if self.current_index < len(self.schedule):
                next_time = self.schedule[self.current_index][0] - self.clock.get_time()
                self.hold_in("active", next_time)
            else:
                self.hold_in("passive", float('inf'))
        else:
            self.hold_in("passive", float('inf'))

    def deltext(self, e):
        # No inputs
        self.hold_in(self.phase, self.sigma - e)

    def lambdaf(self):
        if self.phase == "active" and self.current_index < len(self.schedule):
            _, event_name = self.schedule[self.current_index]
            self.out_cust.add(event_name)
            # Generator is not listed in the spec for output messages, so we skip printing here.

    def exit(self):
        pass


# --- Coupled Model ---

class BarbershopSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None, schedule: list):
        super().__init__(name)
        self.parent = parent
        
        # Components
        self.generator = Generator("generator", self, schedule)
        self.reception = Reception("reception", self)
        self.checkhair = Checkhair("checkhair", self)
        self.cuthair = Cuthair("cuthair", self)
        
        self.add_component(self.generator)
        self.add_component(self.reception)
        self.add_component(self.checkhair)
        self.add_component(self.cuthair)
        
        # Couplings
        # Generator -> Reception
        self.add_coupling(self.generator.out_cust, self.reception.in_newcust)
        
        # Reception -> Checkhair
        self.add_coupling(self.reception.out_cust, self.checkhair.in_cust)
        
        # Checkhair -> Cuthair
        self.add_coupling(self.checkhair.out_to_cut, self.cuthair.in_cust)
        
        # Cuthair -> Checkhair (Feedback loop)
        self.add_coupling(self.cuthair.out_done, self.checkhair.in_cut_done)
        
        # Checkhair -> Reception (Feedback loop)
        self.add_coupling(self.checkhair.out_to_reception, self.reception.in_done)


# --- Main Entry Point ---

def parse_input():
    """Reads stdin and parses schedule."""
    schedule = []
    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2:
                logger.warning(f"Skipping malformed line: {line}")
                continue
            
            time_str, event = parts
            # Parse HH:MM:SS:mm to seconds
            t_parts = time_str.split(':')
            if len(t_parts) != 4:
                logger.warning(f"Invalid time format: {time_str}")
                continue
                
            h, m, s, ms = map(int, t_parts)
            total_sec = h * 3600 + m * 60 + s + ms / 1000.0
            
            if event == "newcust":
                schedule.append((total_sec, event))
            else:
                logger.warning(f"Unknown event type: {event}")
                
    except Exception as e:
        logger.error(f"Error reading input: {e}")
        
    return schedule

def main():
    parser = argparse.ArgumentParser(description="Barbershop Simulation")
    parser.add_argument("--simulation_time", type=float, default=1000000.0, help="Total simulation time")
    args = parser.parse_args()
    
    # 1. Read Input
    schedule = parse_input()
    logger.info(f"Loaded {len(schedule)} events from stdin.")
    
    # 2. Build Model
    root = BarbershopSystem("barbershop", None, schedule)
    
    # 3. Setup Simulation
    clock = SimulationClock(0)
    coord = Coordinator(root, clock=clock)
    
    # 4. Run
    coord.initialize()
    coord.simulate_time(args.simulation_time)
    
    logger.info("Simulation finished.")

if __name__ == "__main__":
    main()