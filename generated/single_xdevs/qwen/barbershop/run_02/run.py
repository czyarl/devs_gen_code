# Your complete run.py implementation here
import sys
import json
import argparse
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class Reception(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.queue = deque()
        self.capacity = 8
        self.total_customers = 0
        self.processing = False
        self.processing_time = 5.0

        # Ports
        self.input["newcust"] = Port(str, "newcust")
        self.output["cust"] = Port(str, "cust")

        # State
        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.processing and self.queue:
            self.output["cust"].add("newcust")

    def deltint(self):
        if self.processing and self.queue:
            self.processing = False
            self.total_customers -= 1
            self.queue.popleft()
            self.hold_in("IDLE", 0)
        else:
            self.hold_in("IDLE", 0)

    def deltext(self, e):
        if "newcust" in self.input["newcust"].values:
            if len(self.queue) < self.capacity:
                self.queue.append("newcust")
                self.total_customers += 1
                # Emit state change
                print(json.dumps({
                    "time": self.clock,
                    "type": "state",
                    "model": "reception",
                    "field": "total customers num",
                    "value": self.total_customers
                }), file=sys.stderr)
            else:
                # Customer ignored
                pass

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
        self.customer = None
        self.processing = False
        self.processing_time = 7.0

        # Ports
        self.input["to_check"] = Port(str, "to_check")
        self.output["to_cut"] = Port(str, "to_cut")
        self.output["to_reception"] = Port(str, "to_reception")

        # State
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
        if "newcust" in self.input["to_check"].values:
            if self.customer is None:
                self.customer = "newcust"
                self.hold_in("PROCESSING", self.processing_time)
            else:
                # Wait for current customer to finish
                pass
        elif "done" in self.input["to_check"].values:
            self.customer = "done"
            self.hold_in("PROCESSING", 0)

    def exit(self):
        pass

class CutHair(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.customer = None
        self.total_customer_done = 0
        self.processing_time = 20.0

        # Ports
        self.input["to_cut"] = Port(str, "to_cut")
        self.output["out"] = Port(str, "out")

        # State
        self.hold_in("IDLE", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.customer == "newcust":
            self.output["out"].add("done")

    def deltint(self):
        if self.customer == "newcust":
            self.total_customer_done += 1
            self.customer = None
            # Emit state change
            print(json.dumps({
                "time": self.clock,
                "type": "state",
                "model": "cuthair",
                "field": "total customer done",
                "value": self.total_customer_done
            }), file=sys.stderr)
            self.hold_in("IDLE", 0)
        else:
            self.hold_in("IDLE", 0)

    def deltext(self, e):
        if "newcust" in self.input["to_cut"].values:
            if self.customer is None:
                self.customer = "newcust"
                self.hold_in("PROCESSING", self.processing_time)
            else:
                # Wait for current customer to finish
                pass

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Instantiate sub-models
        self.reception = Reception(name="reception", parent=self)
        self.checkhair = CheckHair(name="checkhair", parent=self)
        self.cuthair = CutHair(name="cuthair", parent=self)

        self.add_component(self.reception)
        self.add_component(self.checkhair)
        self.add_component(self.cuthair)

        # Define couplings
        self.add_coupling(self.reception.output["cust"], self.checkhair.input["to_check"])
        self.add_coupling(self.checkhair.output["to_cut"], self.cuthair.input["to_cut"])
        self.add_coupling(self.cuthair.output["out"], self.checkhair.input["to_check"])
        self.add_coupling(self.checkhair.output["to_reception"], self.reception.input["newcust"])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args()

    # Read input data
    events = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            time_str, event_name = line.split(' ', 1)
            # Convert time string to float
            h, m, s, ms = map(int, time_str.split(':'))
            time_in_seconds = h * 3600 + m * 60 + s + ms / 1000.0
            events.append((time_in_seconds, event_name))
        except Exception as e:
            print(f"Error parsing input line: {line}", file=sys.stderr)
            continue

    # Sort events by time
    events.sort(key=lambda x: x[0])

    # Build system
    root = System(name="system", parent=None)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()

    # Schedule initial events
    for time_in_seconds, event_name in events:
        if event_name == "newcust":
            coord.schedule(time_in_seconds, root.reception, "newcust", "newcust")

    # Run simulation
    coord.simulate_time(args.simulation_time)

if __name__ == "__main__":
    main()