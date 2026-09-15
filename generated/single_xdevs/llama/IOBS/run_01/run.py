import argparse
import json
import logging
import random
import sys
from collections import defaultdict
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class InputReader(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port("input", "output"))
        self.input_buffer = []

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        if self.phase == "INIT":
            self.output["output"].add({"valid": 1, "invalid": 0})
            self.hold_in("WAIT", 10)

    def exit(self):
        pass

    def run(self, input_str):
        try:
            time_str, valid, invalid = input_str.strip().split()
            time = self.parse_time(time_str)
            valid, invalid = int(valid), int(invalid)
            self.input_buffer.append((time, valid, invalid))
        except Exception as e:
            logging.error(f"Invalid input format: {e}")

    def parse_time(self, time_str):
        hours, minutes, seconds_millis = time_str.split(":")
        hours, minutes, seconds, millis = int(hours), int(minutes), int(seconds_millis.split(":")[0]), int(seconds_millis.split(":")[1])
        time = hours * 3600 + minutes * 60 + seconds + millis / 1000
        return time

class AAM(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("input", "input"))
        self.add_out_port(Port("output", "output"))
        self.valid = 0
        self.invalid = 0

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        if self.phase == "PROCESS":
            if self.valid == 1 and self.invalid == 0:
                self.output["output"].add({})
                self.hold_in("WAIT", 10)
            elif self.valid == 1 and self.invalid == 1:
                self.output["output"].add({})
                self.hold_in("WAIT", 10)

    def deltext(self, e):
        if self.phase == "INIT":
            input_data = self.input["input"].values[0]
            self.valid, self.invalid = input_data["valid"], input_data["invalid"]
            self.hold_in("PROCESS", 10)

    def exit(self):
        pass

class ANV(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("input", "input"))
        self.add_out_port(Port("output", "output"))

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        if self.phase == "INIT":
            pass
            self.hold_in("PROCESS", 10)

    def exit(self):
        pass

    def deltint(self):
        if self.phase == "PROCESS":
            result = random.random() < 0.5
            if result:
                self.output["output"].add({"pass": 1, "fail": 0})
            else:
                self.output["output"].add({"pass": 0, "fail": 1})
            self.hold_in("WAIT", 10)

class PV(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("input", "input"))
        self.add_out_port(Port("output", "output"))
        self.attempts = 0

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        if self.phase == "INIT":
            self.hold_in("PROCESS", 10)

    def exit(self):
        pass

    def deltint(self):
        if self.phase == "PROCESS":
            result = random.random() < 0.5
            if result:
                self.output["output"].add({"success": 1, "attempts": self.attempts})
                self.hold_in("WAIT", 10)
            else:
                self.attempts += 1
                self.hold_in("PROCESS", 10)

class BPM(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("input", "input"))
        self.add_out_port(Port("output", "output"))
        self.balance = 3000

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        if self.phase == "INIT":
            self.hold_in("PROCESS", 10)

    def exit(self):
        pass

    def deltint(self):
        if self.phase == "PROCESS":
            amount = random.randint(0, 40)
            if amount <= self.balance:
                self.output["output"].add({"amount": amount})
                self.balance -= amount
                self.hold_in("WAIT", 10)
            else:
                self.hold_in("WAIT", 10)

class TPM(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("input", "input"))
        self.add_out_port(Port("output", "output"))
        self.balance = 3000
        self.transaction_count = 0

    def initialize(self):
        self.hold_in("INIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        if self.phase == "INIT":
            self.hold_in("PROCESS", 10)

    def exit(self):
        pass

    def deltint(self):
        if self.phase == "PROCESS":
            input_data = self.input["input"].values[0]
            self.balance -= input_data["amount"]
            self.transaction_count += 1
            self.output["output"].add({"remaining": self.balance, "count": self.transaction_count})
            self.hold_in("WAIT", 10)

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.input_reader = InputReader(name="input_reader1", parent=self)
        self.aam = AAM(name="AAM1", parent=self)
        self.anv = ANV(name="ANV1", parent=self)
        self.pv = PV(name="PV1", parent=self)
        self.bpm = BPM(name="BPM1", parent=self)
        self.tpm = TPM(name="TPM1", parent=self)
        self.add_component(self.input_reader)
        self.add_component(self.aam)
        self.add_component(self.anv)
        self.add_component(self.pv)
        self.add_component(self.bpm)
        self.add_component(self.tpm)
        self.add_coupling(self.input_reader.output["output"], self.aam.input["input"])
        self.add_coupling(self.aam.output["output"], self.anv.input["input"])
        self.add_coupling(self.anv.output["output"], self.pv.input["input"])
        self.add_coupling(self.pv.output["output"], self.bpm.input["input"])
        self.add_coupling(self.bpm.output["output"], self.tpm.input["input"])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=10)
    args = parser.parse_args()

    root = System(name="system", parent=None)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    for line in sys.stdin:
        root.input_reader.run(line)
    coord.simulate_time(args.simulation_time)

    print(json.dumps({"time": 0.0, "model": "input_reader1", "event": "start", "data": {}}, indent=4), file=sys.stdout, flush=True)

if __name__ == "__main__":
    main()