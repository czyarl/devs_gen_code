import argparse
import json
import logging
import random
import sys
import time
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class InputReader(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port("input", "output"))

    def initialize(self):
        print(json.dumps({"time": 0.0, "model": "input_reader1", "event": "start", "data": {}}, indent=4), file=sys.stdout, flush=True)
        for line in sys.stdin:
            try:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                timestamp = parts[0].split(":")
                hours, minutes, seconds, milliseconds = int(timestamp[0]), int(timestamp[1]), int(timestamp[2]), int(timestamp[3])
                time_in_seconds = (hours * 3600 + minutes * 60 + seconds) + milliseconds / 1000
                valid = int(parts[1])
                invalid = int(parts[2])
                self.output["output"].add({"valid": valid, "invalid": invalid, "time": time_in_seconds})
                print(json.dumps({"time": time_in_seconds, "model": "input_reader1", "event": "input", "data": {"valid": valid, "invalid": invalid}}, indent=4), file=sys.stdout, flush=True)
            except Exception as e:
                logging.error(f"Error processing input: {e}")

        self.hold_in("wait", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        pass

    def exit(self):
        pass


class AAM(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("input", "input"))
        self.add_out_port(Port("output", "output"))

    def initialize(self):
        self.hold_in("wait", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("wait", 10)

    def deltext(self, e):
        if self.input["input"].has_value():
            data = self.input["input"].get()
            if data["valid"] == 1 and data["invalid"] == 0:
                self.output["output"].add(data)
                print(json.dumps({"time": self.get_time() + 10, "model": "AAM1", "event": "account_generated", "data": {}}, indent=4), file=sys.stdout, flush=True)
            elif data["valid"] == 1 and data["invalid"] == 1:
                print(json.dumps({"time": self.get_time() + 10, "model": "AAM1", "event": "logout", "data": {}}, indent=4), file=sys.stdout, flush=True)

    def exit(self):
        pass


class ANV(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("input", "input"))
        self.add_out_port(Port("output", "output"))

    def initialize(self):
        self.hold_in("wait", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("wait", 10)

    def deltext(self, e):
        if self.input["input"].has_value():
            data = self.input["input"].get()
            pass_verify = random.random() < 0.5
            if pass_verify:
                self.output["output"].add({"pass": 1, "fail": 0})
                print(json.dumps({"time": self.get_time() + 10, "model": "ANV1", "event": "verification", "data": {"pass": 1, "fail": 0}}, indent=4), file=sys.stdout, flush=True)
            else:
                print(json.dumps({"time": self.get_time() + 10, "model": "ANV1", "event": "verification", "data": {"pass": 0, "fail": 1}}, indent=4), file=sys.stdout, flush=True)

    def exit(self):
        pass


class PV(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("input", "input"))
        self.add_out_port(Port("output", "output"))
        self.attempts = 0

    def initialize(self):
        self.hold_in("wait", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("wait", 10)

    def deltext(self, e):
        if self.input["input"].has_value():
            data = self.input["input"].get()
            self.attempts += 1
            if random.random() < 0.5:
                self.output["output"].add({"success": 1, "attempts": self.attempts})
                print(json.dumps({"time": self.get_time() + 10, "model": "PV1", "event": "verification", "data": {"success": 1, "attempts": self.attempts}}, indent=4), file=sys.stdout, flush=True)

    def exit(self):
        pass


class BPM(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("input", "input"))
        self.add_out_port(Port("output", "output"))
        self.balance = 3000

    def initialize(self):
        self.hold_in("wait", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("wait", 10)

    def deltext(self, e):
        if self.input["input"].has_value():
            data = self.input["input"].get()
            amount = random.randint(0, 40)
            while amount > self.balance:
                amount = random.randint(0, 40)
            self.balance -= amount
            self.output["output"].add({"amount": amount})
            print(json.dumps({"time": self.get_time() + 10, "model": "BPM1", "event": "bill", "data": {"amount": amount}}, indent=4), file=sys.stdout, flush=True)

    def exit(self):
        pass


class TPM(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("input", "input"))
        self.add_out_port(Port("output", "output"))
        self.balance = 3000
        self.transaction_count = 0

    def initialize(self):
        self.hold_in("wait", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("wait", 10)

    def deltext(self, e):
        if self.input["input"].has_value():
            data = self.input["input"].get()
            self.balance -= data["amount"]
            self.transaction_count += 1
            self.output["output"].add({"remaining": self.balance, "count": self.transaction_count})
            print(json.dumps({"time": self.get_time() + 10, "model": "TPM1", "event": "transaction", "data": {"remaining": self.balance, "count": self.transaction_count}}, indent=4), file=sys.stdout, flush=True)

    def exit(self):
        pass


class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.input_reader1 = InputReader(name="input_reader1", parent=self)
        self.add_component(self.input_reader1)
        self.aam1 = AAM(name="AAM1", parent=self)
        self.add_component(self.aam1)
        self.anv1 = ANV(name="ANV1", parent=self)
        self.add_component(self.anv1)
        self.pv1 = PV(name="PV1", parent=self)
        self.add_component(self.pv1)
        self.bpm1 = BPM(name="BPM1", parent=self)
        self.add_component(self.bpm1)
        self.tpm1 = TPM(name="TPM1", parent=self)
        self.add_component(self.tpm1)

        self.add_coupling(self.input_reader1.output["output"], self.aam1.input["input"])
        self.add_coupling(self.aam1.output["output"], self.anv1.input["input"])
        self.add_coupling(self.anv1.output["output"], self.pv1.input["input"])
        self.add_coupling(self.pv1.output["output"], self.bpm1.input["input"])
        self.add_coupling(self.bpm1.output["output"], self.tpm1.input["input"])


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