import sys
import json
import argparse
import logging
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Configure logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Helper Functions ---

def parse_time(time_str: str) -> float:
    """Parses HH:MM:SS:mm string to float seconds."""
    try:
        h, m, s, ms = map(int, time_str.split(':'))
        return h * 3600 + m * 60 + s + ms / 1000.0
    except ValueError:
        logger.error(f"Invalid time format: {time_str}")
        return 0.0

def log_state(time: float, model: str, field: str, value):
    """Helper to log state changes to stdout."""
    print(json.dumps({
        "time": time,
        "type": "state",
        "model": model,
        "field": field,
        "value": value
    }), file=sys.stdout, flush=True)

def log_message(time: float, model: str, port: str, content: str):
    """Helper to log message events to stdout."""
    print(json.dumps({
        "time": time,
        "type": "message",
        "model": model,
        "port": port,
        "content": content
    }), file=sys.stdout, flush=True)

# --- Atomic Models ---

class Generator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, schedule: list):
        super().__init__(name)
        self.parent = parent
        self.schedule = schedule
        self.schedule.sort(key=lambda x: x[0])
        self.current_index = 0
        
        self.out_cust = Port(object, "cust")
        self.add_out_port(self.out_cust)
        
        if not self.schedule:
            self.hold_in("passive", float('inf'))
        else:
            self.hold_in("active", self.schedule[0][0])

    def initialize(self):
        self.current_index = 0
        if not self.schedule:
            self.hold_in("passive", float('inf'))
        else:
            self.hold_in("active", self.schedule[0][0])

    def deltint(self):
        self.current_index += 1
        if self.current_index < len(self.schedule):
            next_time = self.schedule[self.current_index][0]
            current_time = self.clock.get_time()
            wait_time = next_time - current_time
            if wait_time < 0: wait_time = 0
            self.hold_in("active", wait_time)
        else:
            self.hold_in("passive", float('inf'))

    def deltext(self, e):
        pass

    def lambdaf(self):
        if self.phase == "active" and self.current_index < len(self.schedule):
            self.out_cust.add(self.schedule[self.current_index][1])

    def exit(self):
        pass


class Reception(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.in_new = Port(object, "new")
        self.in_done = Port(object, "done")
        self.out_cust = Port(object, "cust")
        
        self.add_in_port(self.in_new)
        self.add_in_port(self.in_done)
        self.add_out_port(self.out_cust)
        
        self.queue = []
        self.max_capacity = 8
        self.current_customer = None
        self.processing_time = 5.0
        self.barber_free = True 
        
        self.hold_in("idle", float('inf'))

    def initialize(self):
        self.queue = []
        self.current_customer = None
        self.barber_free = True
        log_state(self.clock.get_time(), "reception", "total customers num", 0)
        self.hold_in("idle", float('inf'))

    def _log_queue_state(self):
        count = len(self.queue) + (1 if self.current_customer else 0)
        log_state(self.clock.get_time(), "reception", "total customers num", count)

    def deltext(self, e):
        if self.in_new:
            for cust in self.in_new.values:
                total = len(self.queue) + (1 if self.current_customer else 0)
                if total < self.max_capacity:
                    self.queue.append(cust)
                    self._log_queue_state()
        
        if self.in_done:
            self.barber_free = True
            if self.phase == "ready":
                self.hold_in("sending", 0.0)
                return

        if self.phase == "idle":
            if self.queue:
                self.current_customer = self.queue.pop(0)
                self._log_queue_state()
                self.hold_in("checkin", self.processing_time)
            else:
                self.hold_in("idle", float('inf'))
        elif self.phase == "checkin":
            self.hold_in("checkin", self.sigma - e)
        elif self.phase == "ready":
            self.hold_in("ready", float('inf'))
        elif self.phase == "sending":
            pass

    def deltint(self):
        if self.phase == "checkin":
            if self.barber_free:
                self.hold_in("sending", 0.0)
            else:
                self.hold_in("ready", float('inf'))
        elif self.phase == "sending":
            self.current_customer = None
            self.barber_free = False
            if self.queue:
                self.current_customer = self.queue.pop(0)
                self._log_queue_state()
                self.hold_in("checkin", self.processing_time)
            else:
                self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "sending" and self.current_customer:
            self.out_cust.add(self.current_customer)
            log_message(self.clock.get_time(), "reception", "cust", "newcust")

    def exit(self):
        pass


class Checkhair(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.in_cust = Port(object, "cust")
        self.in_done_cut = Port(object, "done")
        self.out_cut = Port(object, "to_cut")
        self.out_reception = Port(object, "to_reception")
        
        self.add_in_port(self.in_cust)
        self.add_in_port(self.in_done_cut)
        self.add_out_port(self.out_cut)
        self.add_out_port(self.out_reception)
        
        self.processing_time = 7.0
        self.current_customer = None
        
        self.hold_in("available", float('inf'))

    def initialize(self):
        self.current_customer = None
        log_state(self.clock.get_time(), "checkhair", "customer", "done")
        self.hold_in("available", float('inf'))

    def deltext(self, e):
        if self.in_cust:
            for cust in self.in_cust.values:
                if self.phase == "available":
                    self.current_customer = cust
                    log_state(self.clock.get_time(), "checkhair", "customer", "newcust")
                    self.hold_in("inspecting", self.processing_time)
        
        if self.in_done_cut:
            if self.phase == "waiting_cut":
                self.hold_in("notify", 0.0)

        if self.phase == "available":
            self.hold_in("available", float('inf'))
        elif self.phase == "inspecting":
            self.hold_in("inspecting", self.sigma - e)
        elif self.phase == "waiting_cut":
            self.hold_in("waiting_cut", float('inf'))

    def deltint(self):
        if self.phase == "inspecting":
            self.hold_in("send_cut", 0.0)
        elif self.phase == "send_cut":
            self.hold_in("waiting_cut", float('inf'))
        elif self.phase == "notify":
            self.current_customer = None
            log_state(self.clock.get_time(), "checkhair", "customer", "done")
            self.hold_in("available", float('inf'))

    def lambdaf(self):
        if self.phase == "send_cut":
            self.out_cut.add(self.current_customer)
            log_message(self.clock.get_time(), "checkhair", "to_cut", "newcust")
        elif self.phase == "notify":
            self.out_reception.add("done")
            log_message(self.clock.get_time(), "checkhair", "to_reception", "done")

    def exit(self):
        pass


class Cuthair(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.in_cust = Port(object, "cust")
        self.out_done = Port(object, "out")
        
        self.add_in_port(self.in_cust)
        self.add_out_port(self.out_done)
        
        self.processing_time = 20.0
        self.total_done = 0
        
        self.hold_in("idle", float('inf'))

    def initialize(self):
        self.total_done = 0
        log_state(self.clock.get_time(), "cuthair", "total customer done", 0)
        self.hold_in("idle", float('inf'))

    def deltext(self, e):
        if self.in_cust:
            for cust in self.in_cust.values:
                if self.phase == "idle":
                    self.hold_in("cutting", self.processing_time)
        
        if self.phase == "idle":
            self.hold_in("idle", float('inf'))
        elif self.phase == "cutting":
            self.hold_in("cutting", self.sigma - e)

    def deltint(self):
        if self.phase == "cutting":
            self.total_done += 1
            log_state(self.clock.get_time(), "cuthair", "total customer done", self.total_done)
            self.hold_in("send_done", 0.0)
        elif self.phase == "send_done":
            self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "send_done":
            self.out_done.add("done")
            log_message(self.clock.get_time(), "cuthair", "out", "done")

    def exit(self):
        pass


class BarbershopSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None, schedule: list):
        super().__init__(name)
        self.parent = parent
        
        self.generator = Generator("generator", self, schedule)
        self.reception = Reception("reception", self)
        self.checkhair = Checkhair("checkhair", self)
        self.cuthair = Cuthair("cuthair", self)
        
        self.add_component(self.generator)
        self.add_component(self.reception)
        self.add_component(self.checkhair)
        self.add_component(self.cuthair)
        
        self.add_coupling(self.generator.out_cust, self.reception.in_new)
        self.add_coupling(self.reception.out_cust, self.checkhair.in_cust)
        self.add_coupling(self.checkhair.out_cut, self.cuthair.in_cust)
        self.add_coupling(self.cuthair.out_done, self.checkhair.in_done_cut)
        self.add_coupling(self.checkhair.out_reception, self.reception.in_done)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args()
    
    schedule = []
    for line in sys.stdin:
        line = line.strip()
        if not line: continue
        parts = line.split()
        if len(parts) >= 2:
            t = parse_time(parts[0])
            if parts[1] == "newcust":
                schedule.append((t, "newcust"))
                
    root = BarbershopSystem("barbershop", None, schedule)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulation_time)

if __name__ == "__main__":
    main()