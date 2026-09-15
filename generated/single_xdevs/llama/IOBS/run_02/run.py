import argparse
import json
import logging
import random
import sys
import time
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class InputReader1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port("input", "out"))
        self.input_lines = []

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.input_lines:
            line = self.input_lines.pop(0)
            parts = line.split()
            timestamp = time.strptime(parts[0], "%H:%M:%S:%f")
            timestamp = (timestamp.tm_hour * 3600 + timestamp.tm_min * 60 + timestamp.tm_sec + timestamp.tm_sec / 1000)
            valid = int(parts[1])
            invalid = int(parts[2])
            self.output["out"].add({"valid": valid, "invalid": invalid})
            self.hold_in("WAIT", 10)
        else:
            self.hold_in("END", 0)

    def deltext(self, e):
        if e == "input":
            self.input_lines.append(sys.stdin.readline().strip())
            self.hold_in("PROCESS", 0)

    def exit(self):
        pass

class AAM1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("input", "in"))
        self.add_out_port(Port("output", "out"))
        self.add_out_port(Port("logout", "logout"))

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("WAIT", 10)

    def deltext(self, e):
        if e == "in":
            data = self.input["in"].values[0]
            if data["valid"] == 1 and data["invalid"] == 0:
                self.output["out"].add({})
                print(json.dumps({"time": self.time, "model": "AAM1", "event": "account_generated", "data": {}}), file=sys.stdout, flush=True)
                self.hold_in("WAIT", 10)
            elif data["valid"] == 1 and data["invalid"] == 1:
                self.output["logout"].add({})
                print(json.dumps({"time": self.time, "model": "AAM1", "event": "logout", "data": {}}), file=sys.stdout, flush=True)
                self.hold_in("WAIT", 10)

    def exit(self):
        pass

class ANV1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("input", "in"))
        self.add_out_port(Port("output", "out"))

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("WAIT", 10)

    def deltext(self, e):
        if e == "in":
            data = self.input["in"].values[0]
            pass_verify = random.random() < 0.5
            if pass_verify:
                self.output["out"].add({"pass": 1, "fail": 0})
                print(json.dumps({"time": self.time, "model": "ANV1", "event": "verification", "data": {"pass": 1, "fail": 0}}), file=sys.stdout, flush=True)
            else:
                self.output["out"].add({"pass": 0, "fail": 1})
                print(json.dumps({"time": self.time, "model": "ANV1", "event": "verification", "data": {"pass": 0, "fail": 1}}), file=sys.stdout, flush=True)
            self.hold_in("WAIT", 10)

    def exit(self):
        pass

class PV1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("input", "in"))
        self.add_out_port(Port("output", "out"))
        self.attempts = 0

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("WAIT", 10)

    def deltext(self, e):
        if e == "in":
            self.attempts += 1
            if random.random() < 0.5:
                self.output["out"].add({})
                print(json.dumps({"time": self.time, "model": "PV1", "event": "verification", "data": {"success": 1, "attempts": self.attempts}}), file=sys.stdout, flush=True)
                self.hold_in("WAIT", 10)
            else:
                self.hold_in("WAIT", 10)

    def exit(self):
        pass

class BPM1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("input", "in"))
        self.add_out_port(Port("output", "out"))
        self.balance = 3000

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("WAIT", 10)

    def deltext(self, e):
        if e == "in":
            amount = random.randint(0, 40)
            if amount > self.balance:
                amount = self.balance
            self.balance -= amount
            self.output["out"].add({"amount": amount})
            print(json.dumps({"time": self.time, "model": "BPM1", "event": "bill", "data": {"amount": amount}}), file=sys.stdout, flush=True)
            self.hold_in("WAIT", 10)

    def exit(self):
        pass

class TPM1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("input", "in"))
        self.add_out_port(Port("output", "out"))
        self.balance = 3000
        self.transaction_count = 0

    def initialize(self):
        self.hold_in("INIT", 0)
        print(json.dumps({"time": self.time, "model": "input_reader1", "event": "start", "data": {}}), file=sys.stdout, flush=True)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("WAIT", 10)

    def deltext(self, e):
        if e == "in":
            data = self.input["in"].values[0]
            self.balance -= data["amount"]
            self.transaction_count += 1
            self.output["out"].add({"remaining": self.balance, "count": self.transaction_count})
            print(json.dumps({"time": self.time, "model": "TPM1", "event": "transaction", "data": {"remaining": self.balance, "count": self.transaction_count}}), file=sys.stdout, flush=True)
            self.hold_in("WAIT", 10)

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.input_reader1 = InputReader1(name="input_reader1", parent=self)
        self.add_component(self.input_reader1)
        self.AAM1 = AAM1(name="AAM1", parent=self)
        self.add_component(self.AAM1)
        self.ANV1 = ANV1(name="ANV1", parent=self)
        self.add_component(self.ANV1)
        self.PV1 = PV1(name="PV1", parent=self)
        self.add_component(self.PV1)
        self.BPM1 = BPM1(name="BPM1", parent=self)
        self.add_component(self.BPM1)
        self.TPM1 = TPM1(name="TPM1", parent=self)
        self.add_component(self.TPM1)

        self.add_coupling(self.input_reader1.output["out"], self.AAM1.input["in"])
        self.add_coupling(self.AAM1.output["out"], self.ANV1.input["in"])
        self.add_coupling(self.ANV1.output["out"], self.PV1.input["in"])
        self.add_coupling(self.PV1.output["out"], self.BPM1.input["in"])
        self.add_coupling(self.BPM1.output["out"], self.TPM1.input["in"])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args()

    root = System(name="system", parent=None)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulation_time)

if __name__ == "__main__":
    main()