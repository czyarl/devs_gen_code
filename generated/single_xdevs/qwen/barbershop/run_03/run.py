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
        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.processing and self.queue:
            self.output["cust"].add(self.queue[0])

    def deltint(self):
        if self.processing:
            self.processing = False
            if self.queue:
                self.total_customers -= 1
                self.queue.popleft()
                self.hold_in("IDLE", 0)
            else:
                self.hold_in("IDLE", 0)
        else:
            self.hold_in("IDLE", 0)

    def deltext(self, e):
        if self.input["cust"].values:
            for value in self.input["cust"].values:
                if value == "newcust":
                    if self.total_customers < self.max_queue:
                        self.queue.append("newcust")
                        self.total_customers += 1
                        print(json.dumps({
                            "time": self.clock,
                            "type": "state",
                            "model": "reception",
                            "field": "total customers num",
                            "value": self.total_customers
                        }), file=sys.stderr)
                    else:
                        pass  # Ignore
        if not self.processing and self.queue:
            self.processing = True
            self.hold_in("PROCESSING", self.processing_time)
        else:
            self.hold_in("IDLE", 0)

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
        self.hold_in("AVAILABLE", 0)

    def initialize(self):
        self.hold_in("AVAILABLE", 0)

    def lambdaf(self):
        if self.customer == "newcust":
            self.output["to_cut"].add("newcust")
        elif self.customer == "done":
            self.output["to_reception"].add("done")

    def deltint(self):
        if self.customer == "newcust":
            self.customer = "processing"
            self.hold_in("PROCESSING", self.processing_time)
        elif self.customer == "done":
            self.customer = None
            self.hold_in("AVAILABLE", 0)
        else:
            self.hold_in("AVAILABLE", 0)

    def deltext(self, e):
        if self.input["to_check"].values:
            for value in self.input["to_check"].values:
                if value == "newcust":
                    if self.customer is None:
                        self.customer = "newcust"
                        self.hold_in("PROCESSING", self.processing_time)
                    else:
                        # Queue the customer
                        self.customer = "newcust"
                        self.hold_in("PROCESSING", self.processing_time)
        elif self.input["to_cut"].values:
            for value in self.input["to_cut"].values:
                if value == "done":
                    self.customer = "done"
                    self.hold_in("PROCESSING", 0)

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
        self.hold_in("AVAILABLE", 0)

    def initialize(self):
        self.hold_in("AVAILABLE", 0)

    def lambdaf(self):
        if self.customer == "newcust":
            self.output["out"].add("newcust")
        elif self.customer == "done":
            self.total_customer_done += 1
            print(json.dumps({
                "time": self.clock,
                "type": "state",
                "model": "cuthair",
                "field": "total customer done",
                "value": self.total_customer_done
            }), file=sys.stderr)

    def deltint(self):
        if self.customer == "newcust":
            self.customer = "processing"
            self.hold_in("PROCESSING", self.processing_time)
        elif self.customer == "done":
            self.customer = None
            self.hold_in("AVAILABLE", 0)
        else:
            self.hold_in("AVAILABLE", 0)

    def deltext(self, e):
        if self.input["to_cut"].values:
            for value in self.input["to_cut"].values:
                if value == "newcust":
                    if self.customer is None:
                        self.customer = "newcust"
                        self.hold_in("PROCESSING", self.processing_time)
                    else:
                        # Queue the customer
                        self.customer = "newcust"
                        self.hold_in("PROCESSING", self.processing_time)
        elif self.input["out"].values:
            for value in self.input["out"].values:
                if value == "done":
                    self.customer = "done"
                    self.hold_in("PROCESSING", 0)

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.reception = Reception(name="reception", parent=self)
        self.checkhair = CheckHair(name="checkhair", parent=self)
        self.cuthair = CutHair(name="cuthair", parent=self)
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

    root = System(name="system", parent=None)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()

    # Read input from stdin
    lines = sys.stdin.readlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split(" ", 1)
        if len(parts) != 2:
            continue
        time_str, event_name = parts
        if event_name != "newcust":
            continue
        time = parse_time(time_str)
        coord.schedule_event("reception", "cust", "newcust", time)
    
    # Start simulation
    coord.simulate_time(args.simulation_time)

if __name__ == "__main__":
    main()