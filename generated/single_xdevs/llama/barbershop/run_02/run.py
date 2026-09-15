import argparse
import json
import logging
import sys
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class Reception(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("newcust", "in"))
        self.add_out_port(Port("newcust", "cust"))
        self.queue = deque()
        self.total_customers = 0

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        if self.input["in"].has_message():
            if len(self.queue) < 8:
                self.queue.append(e)
                self.total_customers += 1
                self.output["cust"].add("newcust")
                print(json.dumps({"time": self.time, "type": "state", "model": "reception", "field": "total customers", "value": self.total_customers}), file=sys.stdout, flush=True)
                print(json.dumps({"time": self.time, "type": "message", "model": "reception", "port": "cust", "content": "newcust"}), file=sys.stdout, flush=True)
        self.hold_in("WAIT", 0)

    def exit(self):
        pass

    def process_customer(self):
        if self.queue:
            customer = self.queue.popleft()
            self.hold_in("PROCESS", 5)
        else:
            self.hold_in("WAIT", 0)

    def delta(self, e):
        if self.phase == "PROCESS":
            self.output["cust"].add("newcust")
            print(json.dumps({"time": self.time, "type": "message", "model": "reception", "port": "cust", "content": "newcust"}), file=sys.stdout, flush=True)
            self.process_customer()

class CheckHair(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("newcust", "in"))
        self.add_out_port(Port("newcust", "to_cut"))
        self.add_out_port(Port("done", "to_reception"))
        self.customer = None

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        if self.input["in"].has_message():
            self.customer = "newcust"
            print(json.dumps({"time": self.time, "type": "state", "model": "checkhair", "field": "customer", "value": self.customer}), file=sys.stdout, flush=True)
            self.output["to_cut"].add("newcust")
            print(json.dumps({"time": self.time, "type": "message", "model": "checkhair", "port": "to_cut", "content": "newcust"}), file=sys.stdout, flush=True)
        self.hold_in("WAIT", 0)

    def exit(self):
        pass

    def delta(self, e):
        if self.phase == "WAIT":
            self.hold_in("PROCESS", 7)
        elif self.phase == "PROCESS":
            self.customer = "done"
            print(json.dumps({"time": self.time, "type": "state", "model": "checkhair", "field": "customer", "value": self.customer}), file=sys.stdout, flush=True)
            self.output["to_reception"].add("done")
            print(json.dumps({"time": self.time, "type": "message", "model": "checkhair", "port": "to_reception", "content": "done"}), file=sys.stdout, flush=True)
            self.hold_in("WAIT", 0)

class CutHair(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("newcust", "in"))
        self.add_out_port(Port("done", "out"))
        self.total_customers_done = 0

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        if self.input["in"].has_message():
            self.hold_in("PROCESS", 20)

    def exit(self):
        pass

    def delta(self, e):
        if self.phase == "PROCESS":
            self.total_customers_done += 1
            print(json.dumps({"time": self.time, "type": "state", "model": "cuthair", "field": "total customer done", "value": self.total_customers_done}), file=sys.stdout, flush=True)
            self.output["out"].add("done")
            print(json.dumps({"time": self.time, "type": "message", "model": "cuthair", "port": "out", "content": "done"}), file=sys.stdout, flush=True)
            self.hold_in("WAIT", 0)

class Barbershop(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.reception = Reception(name="reception", parent=self)
        self.checkhair = CheckHair(name="checkhair", parent=self)
        self.cuthair = CutHair(name="cuthair", parent=self)
        self.add_component(self.reception)
        self.add_component(self.checkhair)
        self.add_component(self.cuthair)
        self.add_coupling(self.reception.output["cust"], self.checkhair.input["in"])
        self.add_coupling(self.checkhair.output["to_cut"], self.cuthair.input["in"])
        self.add_coupling(self.cuthair.output["out"], self.checkhair.input["in"])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args()

    root = Barbershop(name="barbershop", parent=None)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()

    for line in sys.stdin:
        try:
            time, event = line.strip().split(": ", 1)
            hours, minutes, seconds, _ = map(int, time.split(":"))
            time_in_seconds = hours * 3600 + minutes * 60 + seconds
            coord.schedule_event(time_in_seconds, event)
        except ValueError:
            pass

    coord.simulate_time(args.simulation_time)

if __name__ == "__main__":
    main()