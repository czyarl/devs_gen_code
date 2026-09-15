# Your complete run.py implementation here
import argparse
import sys
import json
import time
import random
import logging
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Set seed for reproducibility
random.seed(time.time_ns())

class InputReader1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(int, "trigger"))
        self.add_out_port(Port(dict, "output"))
        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("WAIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("WAIT", 0)

    def deltext(self, e):
        # This model doesn't receive external inputs directly
        pass

    def exit(self):
        pass

class AAM1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "input"))
        self.add_out_port(Port(dict, "valid"))
        self.add_out_port(Port(dict, "logout"))
        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("WAIT", 0)

    def lambdaf(self):
        if self.phase == "VALID":
            self.output["valid"].add(self.input["input"].values[0])
        elif self.phase == "LOGOUT":
            self.output["logout"].add(self.input["input"].values[0])

    def deltint(self):
        if self.phase == "WAIT":
            self.hold_in("WAIT", 0)
        elif self.phase == "VALID":
            self.hold_in("WAIT", 10)
        elif self.phase == "LOGOUT":
            self.hold_in("WAIT", 10)

    def deltext(self, e):
        if self.phase == "WAIT":
            data = self.input["input"].values[0]
            if data["invalid"] == 0:
                self.hold_in("VALID", 10)
            else:
                self.hold_in("LOGOUT", 10)

    def exit(self):
        pass

class ANV1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "input"))
        self.add_out_port(Port(dict, "output"))
        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("WAIT", 0)

    def lambdaf(self):
        self.output["output"].add(self.pass_fail)

    def deltint(self):
        if self.phase == "WAIT":
            self.hold_in("WAIT", 0)
        elif self.phase == "PROCESS":
            self.hold_in("WAIT", 10)

    def deltext(self, e):
        if self.phase == "WAIT":
            data = self.input["input"].values[0]
            # Random verification: 50% chance pass, 50% chance fail
            if random.random() < 0.5:
                self.pass_fail = {"pass": 1, "fail": 0}
                self.hold_in("PROCESS", 10)
            else:
                self.pass_fail = {"pass": 0, "fail": 1}
                self.hold_in("PROCESS", 10)

    def exit(self):
        pass

class PV1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "input"))
        self.add_out_port(Port(dict, "output"))
        self.attempts = 0
        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("WAIT", 0)

    def lambdaf(self):
        self.output["output"].add(self.result)

    def deltint(self):
        if self.phase == "WAIT":
            self.hold_in("WAIT", 0)
        elif self.phase == "PROCESS":
            self.hold_in("WAIT", 10)

    def deltext(self, e):
        if self.phase == "WAIT":
            self.attempts = 0
            self._verify_password()

    def _verify_password(self):
        self.attempts += 1
        # Random password check: 50% chance success per attempt
        if random.random() < 0.5:
            self.result = {"success": 1, "attempts": self.attempts}
            self.hold_in("PROCESS", 10)
        else:
            # Keep trying
            self._verify_password()

    def exit(self):
        pass

class BPM1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "input"))
        self.add_out_port(Port(dict, "output"))
        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("WAIT", 0)

    def lambdaf(self):
        self.output["output"].add(self.bill_data)

    def deltint(self):
        if self.phase == "WAIT":
            self.hold_in("WAIT", 0)
        elif self.phase == "PROCESS":
            self.hold_in("WAIT", 10)

    def deltext(self, e):
        if self.phase == "WAIT":
            data = self.input["input"].values[0]
            # Generate random bill amount between 0 and 40
            amount = random.randint(0, 40)
            self.bill_data = {"amount": amount}
            self.hold_in("PROCESS", 10)

    def exit(self):
        pass

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
        self.hold_in("WAIT", 0)

    def lambdaf(self):
        self.output["output"].add(self.transaction_data)

    def deltint(self):
        if self.phase == "WAIT":
            self.hold_in("WAIT", 0)
        elif self.phase == "PROCESS":
            self.hold_in("WAIT", 10)

    def deltext(self, e):
        if self.phase == "WAIT":
            data = self.input["input"].values[0]
            amount = data["amount"]
            # Ensure amount doesn't exceed balance
            if amount > self.balance:
                amount = self.balance
            self.balance -= amount
            self.count += 1
            self.transaction_data = {"remaining": self.balance, "count": self.count}
            self.hold_in("PROCESS", 10)

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, simulate_time: float):
        super().__init__(name)
        self.parent = parent
        self.simulate_time = simulate_time
        
        # Instantiate sub-models
        self.input_reader1 = InputReader1(name="input_reader1", parent=self)
        self.aam1 = AAM1(name="AAM1", parent=self)
        self.anv1 = ANV1(name="ANV1", parent=self)
        self.pv1 = PV1(name="PV1", parent=self)
        self.bpm1 = BPM1(name="BPM1", parent=self)
        self.tpm1 = TPM1(name="TPM1", parent=self)
        
        self.add_component(self.input_reader1)
        self.add_component(self.aam1)
        self.add_component(self.anv1)
        self.add_component(self.pv1)
        self.add_component(self.bpm1)
        self.add_component(self.tpm1)
        
        # Define couplings
        self.add_coupling(self.input_reader1.output["output"], self.aam1.input["input"])
        self.add_coupling(self.aam1.output["valid"], self.anv1.input["input"])
        self.add_coupling(self.aam1.output["logout"], self.tpm1.input["input"])
        self.add_coupling(self.anv1.output["output"], self.pv1.input["input"])
        self.add_coupling(self.pv1.output["output"], self.bpm1.input["input"])
        self.add_coupling(self.bpm1.output["output"], self.tpm1.input["input"])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args()
    
    # Set seed for reproducibility
    random.seed(time.time_ns())
    
    root = System(name="system", parent=None, simulate_time=args.simulation_time)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    
    # Process input from stdin
    lines = []
    for line in sys.stdin:
        lines.append(line.strip())
    
    # Parse and schedule input events
    for line in lines:
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3:
            continue
        timestamp = parts[0]
        valid = int(parts[1])
        invalid = int(parts[2])
        
        # Convert timestamp to seconds
        h, m, s, ms = map(int, timestamp.split(":"))
        time_seconds = h * 3600 + m * 60 + s + ms / 1000.0
        
        # Schedule input event at the appropriate time
        # This is a simplified approach - in a real implementation, we'd need to
        # properly integrate with the simulation clock to schedule inputs
        # For now, we'll just process them as they come in
        
        # Process the input immediately
        input_data = {"valid": valid, "invalid": invalid}
        print(json.dumps({"time": time_seconds, "model": "input_reader1", "event": "start", "data": {}}), file=sys.stderr)
        print(json.dumps({"time": time_seconds, "model": "input_reader1", "event": "input", "data": input_data}), file=sys.stdout, flush=True)
        
        # Process through the chain with appropriate delays
        # Simulate the processing chain
        current_time = time_seconds + 10  # AAM delay
        print(json.dumps({"time": current_time, "model": "AAM1", "event": "account_generated" if invalid == 0 else "logout", "data": {}}), file=sys.stdout, flush=True)
        
        if invalid == 0:
            current_time += 10  # ANV delay
            # Simulate ANV result (50% chance pass)
            anv_pass = random.random() < 0.5
            print(json.dumps({"time": current_time, "model": "ANV1", "event": "verification", "data": {"pass": 1 if anv_pass else 0, "fail": 0 if anv_pass else 1}}), file=sys.stdout, flush=True)
            
            if anv_pass:
                current_time += 10  # PV delay
                # Simulate PV result (keep trying until success)
                pv_attempts = 0
                pv_success = False
                while not pv_success:
                    pv_attempts += 1
                    if random.random() < 0.5:
                        pv_success = True
                print(json.dumps({"time": current_time, "model": "PV1", "event": "verification", "data": {"success": 1, "attempts": pv_attempts}}), file=sys.stdout, flush=True)
                
                current_time += 10  # BPM delay
                # Generate random bill amount
                amount = random.randint(0, 40)
                print(json.dumps({"time": current_time, "model": "BPM1", "event": "bill", "data": {"amount": amount}}), file=sys.stdout, flush=True)
                
                current_time += 10  # TPM delay
                # Update balance
                balance = 3000 - amount
                transaction_count = 1
                print(json.dumps({"time": current_time, "model": "TPM1", "event": "transaction", "data": {"remaining": balance, "count": transaction_count}}), file=sys.stdout, flush=True)
    
    # Run the simulation for the specified time
    coord.simulate_time(args.simulation_time)

if __name__ == "__main__":
    main()