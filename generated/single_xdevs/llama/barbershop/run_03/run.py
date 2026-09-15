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
        self.hold_in("idle", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "processing":
            self.total_customers += 1
            self.queue.append("newcust")
            self.output["cust"].add("newcust")
            self.hold_in("processing", 5)
        else:
            self.hold_in("idle", 0)

    def deltext(self, e):
        if self.phase == "idle" and len(self.queue) < 8:
            self.hold_in("processing", 0)
        else:
            self.hold_in("idle", 0)

    def exit(self):
        print(json.dumps({"time": self.time, "type": "state", "model": "reception", "field": "total customers", "value": len(self.queue)}), file=sys.stdout, flush=True)


class HairInspection(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("newcust", "in"))
        self.add_out_port(Port("newcust", "to_cut"))
        self.add_out_port(Port("done", "to_reception"))
        self.customer = None

    def initialize(self):
        self.hold_in("available", 0)

    def lambdaf(self):
        if self.phase == "processing":
            self.output["to_cut"].add("newcust")

    def deltint(self):
        if self.phase == "processing":
            self.customer = "newcust"
            self.hold_in("busy", 7)
        elif self.phase == "busy":
            self.hold_in("available", 0)

    def deltext(self, e):
        if self.phase == "available":
            self.hold_in("processing", 0)
        else:
            self.hold_in("busy", 0)

    def exit(self):
        pass


class HairCutting(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("newcust", "in"))

    def initialize(self):
        self.hold_in("idle", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("cutting", 20)

    def deltext(self, e):
        self.hold_in("idle", 0)

    def exit(self):
        pass


class Barbershop(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.reception = Reception(name="reception", parent=self)
        self.hair_inspection = HairInspection(name="checkhair", parent=self)
        self.hair_cutting = HairCutting(name="cuthair", parent=self)
        self.add_component(self.reception)
        self.add_component(self.hair_inspection)
        self.add_component(self.hair_cutting)
        self.add_coupling(self.reception.output["cust"], self.hair_inspection.input["in"])
        self.add_coupling(self.hair_inspection.output["to_cut"], self.hair_cutting.input["in"])
        self.add_coupling(self.hair_cutting.output["out"], self.hair_inspection.input["in"])


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
            if event == "newcust":
                root.reception.input["in"].add("newcust")
        except Exception as e:
            logging.error(f"Error processing line: {e}")

    coord.simulate_time(args.simulation_time)

if __name__ == "__main__":
    main()