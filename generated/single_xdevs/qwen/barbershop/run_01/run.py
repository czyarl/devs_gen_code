# Your complete run.py implementation here
import argparse
import sys
import json
import logging
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class Reception(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(str, "cust"))
        self.add_out_port(Port(str, "cust"))
        self.queue = deque()
        self.total_customers = 0
        self.processing = False
        self.processing_time = 5.0
        self.max_queue = 8
        self.initialize()

    def initialize(self):
        self.hold_in("WAIT", 0)

    def lambdaf(self):
        if self.processing and self.queue:
            self.output["cust"].add(self.queue[0])

    def deltint(self):
        if self.processing and self.queue:
            self.processing = False
            self.total_customers -= 1
            self.queue.popleft()
            if self.queue:
                self.processing = True
                self.hold_in("PROCESS", self.processing_time)
            else:
                self.hold_in("WAIT", 0)
        else:
            self.hold_in("WAIT", 0)

    def deltext(self, e):
        if self.input["cust"].values:
            customer = self.input["cust"].values[0]
            if self.total_customers < self.max_queue:
                self.queue.append(customer)
                self.total_customers += 1
                if not self.processing:
                    self.processing = True
                    self.hold_in("PROCESS", self.processing_time)
                else:
                    self.hold_in("WAIT", 0)
            else:
                # Customer ignored, no change in queue
                self.hold_in("WAIT", 0)
        else:
            self.hold_in("WAIT", 0)

    def exit(self):
        pass

class CheckHair(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(str, "to_check"))
        self.add_out_port(Port(str, "to_cut"))
        self.add_out_port(Port(str, "to_reception"))
        self.customer = None
        self.processing_time = 7.0
        self.initialize()

    def initialize(self):
        self.hold_in("AVAILABLE", 0)

    def lambdaf(self):
        if self.customer == "newcust":
            self.output["to_cut"].add("newcust")
        elif self.customer == "done":
            self.output["to_reception"].add("done")

    def deltint(self):
        if self.customer == "newcust":
            self.customer = None
            self.hold_in("AVAILABLE", 0)
        elif self.customer == "done":
            self.customer = None
            self.hold_in("AVAILABLE", 0)
        else:
            self.hold_in("AVAILABLE", 0)

    def deltext(self, e):
        if self.input["to_check"].values:
            self.customer = "newcust"
            self.hold_in("PROCESS", self.processing_time)
        elif self.input["to_cut"].values and self.customer == "done":
            self.customer = "done"
            self.hold_in("PROCESS", 0)
        else:
            self.hold_in("AVAILABLE", 0)

    def exit(self):
        pass

class CutHair(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(str, "to_cut"))
        self.add_out_port(Port(str, "out"))
        self.customer = None
        self.processing_time = 20.0
        self.total_customer_done = 0
        self.initialize()

    def initialize(self):
        self.hold_in("AVAILABLE", 0)

    def lambdaf(self):
        if self.customer == "newcust":
            self.output["out"].add("newcust")
        elif self.customer == "done":
            self.output["out"].add("done")

    def deltint(self):
        if self.customer == "newcust":
            self.customer = None
            self.total_customer_done += 1
            self.hold_in("AVAILABLE", 0)
        elif self.customer == "done":
            self.customer = None
            self.hold_in("AVAILABLE", 0)
        else:
            self.hold_in("AVAILABLE", 0)

    def deltext(self, e):
        if self.input["to_cut"].values:
            self.customer = "newcust"
            self.hold_in("PROCESS", self.processing_time)
        else:
            self.hold_in("AVAILABLE", 0)

    def exit(self):
        pass

class BarbershopSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.reception = Reception("reception", self)
        self.checkhair = CheckHair("checkhair", self)
        self.cuthair = CutHair("cuthair", self)
        self.add_component(self.reception)
        self.add_component(self.checkhair)
        self.add_component(self.cuthair)
        self.add_coupling(self.reception.output["cust"], self.checkhair.input["to_check"])
        self.add_coupling(self.checkhair.output["to_cut"], self.cuthair.input["to_cut"])
        self.add_coupling(self.cuthair.output["out"], self.checkhair.input["to_cut"])
        self.add_coupling(self.checkhair.output["to_reception"], self.reception.input["cust"])

def parse_time(time_str):
    h, m, s, ms = map(int, time_str.split(":"))
    return h * 3600 + m * 60 + s + ms / 1000.0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args()

    # Read input from stdin
    events = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        time_str, event_name = line.split(" ", 1)
        event_time = parse_time(time_str)
        events.append((event_time, event_name))

    # Sort events by time
    events.sort(key=lambda x: x[0])

    # Create system
    root = BarbershopSystem(name="barbershop", parent=None)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()

    # Schedule initial events
    for event_time, event_name in events:
        if event_name == "newcust":
            coord.schedule_event(event_time, "reception", "cust", "newcust")

    # Run simulation
    coord.simulate_time(args.simulation_time)

if __name__ == "__main__":
    main()