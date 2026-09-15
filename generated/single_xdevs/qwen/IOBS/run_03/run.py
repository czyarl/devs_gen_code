```python
import argparse
import sys
import json
import time
import random
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Set random seed
random.seed(time.time_ns())

class input_reader1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "input"))
        self.add_out_port(Port(dict, "output"))
        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)
        self.log_event("start", {})

    def lambdaf(self):
        if self.output:
            self.output["output"].add(self.output["output"].values[0])

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        # Parse input line
        line = self.input["input"].values[0]
        try:
            timestamp_str, valid_str, invalid_str = line.strip().split()
            valid = int(valid_str)
            invalid = int(invalid_str)
            self.log_event("input", {"valid": valid, "invalid": invalid})
            self.output["output"].add({"valid": valid, "invalid": invalid, "timestamp": timestamp_str})
        except Exception as ex:
            print(f"Error parsing input: {ex}", file=sys.stderr)
        self.hold_in("IDLE", 0)

    def exit(self):
        pass

    def log_event(self, event, data):
        print(json.dumps({"time": self.get_time(), "model": self.name, "event": event, "data": data}), file=sys.stdout, flush=True)

class AAM1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "input"))
        self.add_out_port(Port(dict, "output"))
        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.output:
            self.output["output"].add(self.output["output"].values[0])

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        data = self.input["input"].values[0]
        valid = data["valid"]
        invalid = data["invalid"]
        if valid == 1 and invalid == 0:
            self.log_event("account_generated", {})
            self.output["output"].add(data)
        elif valid == 1 and invalid == 1:
            self.log_event("logout", {})
        self.hold_in("IDLE", 10)

    def exit(self):
        pass

    def log_event(self, event, data):
        print(json.dumps({"time": self.get_time(), "model": self.name, "event": event, "data": data}), file=sys.stdout, flush=True)

class ANV1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "input"))
        self.add_out_port(Port(dict, "output"))
        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.output:
            self.output["output"].add(self.output["output"].values[0])

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        data = self.input["input"].values[0]
        # 50% chance pass
        pass_result = random.randint(0, 1)
        fail_result = 1 - pass_result
        self.log_event("verification", {"pass": pass_result, "fail": fail_result})
        if pass_result == 1:
            self.output["output"].add(data)
        self.hold_in("IDLE", 10)

    def exit(self):
        pass

    def log_event(self, event, data):
        print(json.dumps({"time": self.get_time(), "model": self.name, "event": event, "data": data}), file=sys.stdout, flush=True)

class PV1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "input"))
        self.add_out_port(Port(dict, "output"))
        self.attempts = 0
        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.output:
            self.output["output"].add(self.output["output"].values[0])

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        data = self.input["input"].values[0]
        self.attempts = 0
        self.check_password(data)

    def check_password(self, data):
        # 50% chance success per attempt
        success = random.randint(0, 1)
        self.attempts += 1
        if success == 1:
            self.log_event("verification", {"success": 1, "attempts": self.attempts})
            self.output["output"].add(data)
            self.hold_in("IDLE", 10)
        else:
            self.check_password(data)

    def exit(self):
        pass

    def log_event(self, event, data):
        print(json.dumps({"time": self.get_time(), "model": self.name, "event": event, "data": data}), file=sys.stdout, flush=True)

class BPM1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "input"))
        self.add_out_port(Port(dict, "output"))
        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.output:
            self.output["output"].add(self.output["output"].values[0])

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        data = self.input["input"].values[0]
        # Generate random bill amount between 0 and 40
        amount = random.randint(0, 40)
        self.log_event("bill", {"amount": amount})
        self.output["output"].add({"amount": amount})
        self.hold_in("IDLE", 10)

    def exit(self):
        pass

    def log_event(self, event, data):
        print(json.dumps({"time": self.get_time(), "model": self.name, "event": event, "data": data}), file=sys.stdout, flush=True)

class TPM1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "input"))
        self.add_out_port(Port(dict, "output"))
        self.balance = 3000
        self.count = 0
        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.output:
            self.output["output"].add(self.output["output"].values[0])

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        data = self.input["input"].values[0]
        amount = data["amount"]
        self.balance -= amount
        self.count += 1
        self.log_event("transaction", {"remaining": self.balance, "count": self.count})
        self.output["output"].add({"remaining": self.balance, "count": self.count})
        self.hold_in("IDLE", 10)

    def exit(self):
        pass

    def log_event(self, event, data):
        print(json.dumps({"time": self.get_time(), "model": self.name, "event": event, "data": data}), file=sys.stdout, flush=True)

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        self.input_reader1 = input_reader1(name="input_reader1", parent=self)
        self.AAM1 = AAM1(name="AAM1", parent=self)
        self.ANV1 = ANV1(name="ANV1", parent=self)
        self.PV1 = PV1(name="PV1", parent=self)
        self.BPM1 = BPM1(name="BPM1", parent=self)
        self.TPM1 = TPM1(name="TPM1", parent=self)

        self.add_component(self.input_reader1)
        self.add_component(self.AAM1)
        self.add_component(self.ANV1)
        self.add_component(self.PV1)
        self.add_component(self.BPM1)
        self.add_component(self.TPM1)

        self.add_coupling(self.input_reader1.output["output"], self.AAM1.input["input"])
        self.add_coupling(self.AAM1.output["output"], self.ANV1.input["input"])
        self.add_coupling(self.ANV1.output["output"], self.PV1.input["input"])
        self.add_coupling(self.PV1.output["output"], self.BPM1.input["input"])
        self.add_coupling(self.BPM1.output["output"], self.TPM1.input["input"])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args()

    root = System(name="system", parent=None)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()

    # Read input from stdin line by line
    for line in sys.stdin:
        # Schedule input_reader1 to process input
        input_reader = root.input_reader1
        input_reader.deltext(0)
        input_reader.input["input"].add(line)
        coord.advance()
    
    coord.simulate_time(args.simulation_time)

if __name__ == "__main__":
    main()
</python_code>
```