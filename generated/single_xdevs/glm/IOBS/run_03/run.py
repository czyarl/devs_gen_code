import sys
import json
import argparse
import random
import time
import logging
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Set up logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Global constants
PROCESSING_DELAY = 10.0

def log_event(time_val, model_name, event_name, data):
    """Helper to print JSONL to stdout."""
    output = {
        "time": time_val,
        "model": model_name,
        "event": event_name,
        "data": data
    }
    print(json.dumps(output), file=sys.stdout, flush=True)

class InputReader(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.add_out_port(Port(dict, "out"))
        
        # State
        self.requests = deque()
        self.current_request = None
        
        # Phase: "idle", "waiting", "output"
        self.hold_in("idle", float('inf'))

    def initialize(self):
        # Read all input from stdin initially
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) != 3:
                    logger.warning(f"Skipping malformed line: {line}")
                    continue
                
                time_str, valid_str, invalid_str = parts
                valid = int(valid_str)
                invalid = int(invalid_str)
                
                # Parse HH:MM:SS:mmm
                h, m, s, ms = map(int, time_str.split(':'))
                timestamp = h * 3600 + m * 60 + s + ms / 1000.0
                
                self.requests.append({
                    "time": timestamp,
                    "valid": valid,
                    "invalid": invalid
                })
        except Exception as e:
            logger.error(f"Error reading input: {e}")
            
        # Log start event at t=0
        log_event(0.0, "input_reader1", "start", {})
        
        # Schedule first check
        if self.requests:
            first_req_time = self.requests[0]["time"]
            self.hold_in("waiting", first_req_time)
        else:
            self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "output" and self.current_request:
            self.output["out"].add(self.current_request)

    def deltint(self):
        if self.phase == "waiting":
            # Time to process the next request
            if self.requests:
                req = self.requests.popleft()
                self.current_request = req
                
                # Log input event at current time (which is req["time"])
                log_event(self.clock.get_time(), "input_reader1", "input", {
                    "valid": req["valid"],
                    "invalid": req["invalid"]
                })
                
                # Output immediately
                self.hold_in("output", 0.0)
            else:
                self.hold_in("idle", float('inf'))
        elif self.phase == "output":
            # Just finished sending, wait for next
            self.current_request = None
            if self.requests:
                next_req_time = self.requests[0]["time"]
                current_time = self.clock.get_time()
                wait_time = next_req_time - current_time
                if wait_time < 0:
                    wait_time = 0
                self.hold_in("waiting", wait_time)
            else:
                self.hold_in("idle", float('inf'))

    def deltext(self, e):
        # InputReader doesn't receive input
        pass

    def exit(self):
        pass

class AAM(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out"))
        
        self.current_data = None
        self.hold_in("idle", float('inf'))

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "output" and self.current_data:
            self.output["out"].add(self.current_data)

    def deltint(self):
        if self.phase == "processing":
            # Finished processing, ready to output
            log_event(self.clock.get_time(), "AAM1", "account_generated", {})
            self.hold_in("output", 0.0)
        elif self.phase == "processing_logout":
            log_event(self.clock.get_time(), "AAM1", "logout", {})
            self.hold_in("idle", float('inf'))
        elif self.phase == "output":
            self.current_data = None
            self.hold_in("idle", float('inf'))

    def deltext(self, e):
        if self.phase == "idle":
            data = self.input["in"].values
            if data:
                req = list(data)[0]
                
                valid = req.get("valid", 0)
                invalid = req.get("invalid", 0)
                
                if valid == 1 and invalid == 0:
                    # Valid login, forward to ANV
                    self.current_data = req
                    self.hold_in("processing", PROCESSING_DELAY)
                elif valid == 1 and invalid == 1:
                    # Invalid login, trigger logout
                    self.hold_in("processing_logout", PROCESSING_DELAY)
                else:
                    self.hold_in("idle", float('inf'))

    def exit(self):
        pass

class ANV(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out"))
        
        self.current_data = None
        self.verification_result = None 
        self.hold_in("idle", float('inf'))

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "output" and self.current_data and self.verification_result == 1:
            self.output["out"].add(self.current_data)

    def deltint(self):
        if self.phase == "processing":
            if self.verification_result == 1:
                log_event(self.clock.get_time(), "ANV1", "verification", {"pass": 1, "fail": 0})
                self.hold_in("output", 0.0)
            else:
                log_event(self.clock.get_time(), "ANV1", "verification", {"pass": 0, "fail": 1})
                self.hold_in("idle", float('inf'))
        elif self.phase == "output":
            self.current_data = None
            self.verification_result = None
            self.hold_in("idle", float('inf'))

    def deltext(self, e):
        if self.phase == "idle":
            data = self.input["in"].values
            if data:
                req = list(data)[0]
                
                # Random verification: 50% pass, 50% fail
                pass_check = random.choice([True, False])
                
                self.current_data = req
                if pass_check:
                    self.verification_result = 1
                else:
                    self.verification_result = 0
                
                self.hold_in("processing", PROCESSING_DELAY)

    def exit(self):
        pass

class PV(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out"))
        
        self.current_data = None
        self.attempts = 0
        self.hold_in("idle", float('inf'))

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "output" and self.current_data:
            self.output["out"].add(self.current_data)

    def deltint(self):
        if self.phase == "processing":
            # Determine attempts
            self.attempts = 1
            while random.random() < 0.5:
                self.attempts += 1
            
            log_event(self.clock.get_time(), "PV1", "verification", {
                "success": 1, 
                "attempts": self.attempts
            })
            
            self.hold_in("output", 0.0)
        elif self.phase == "output":
            self.current_data = None
            self.attempts = 0
            self.hold_in("idle", float('inf'))

    def deltext(self, e):
        if self.phase == "idle":
            data = self.input["in"].values
            if data:
                self.current_data = list(data)[0]
                self.hold_in("processing", PROCESSING_DELAY)

    def exit(self):
        pass

class BPM(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out"))
        
        self.current_data = None
        self.amount = 0
        self.hold_in("idle", float('inf'))

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "output" and self.current_data:
            self.output["out"].add(self.current_data)

    def deltint(self):
        if self.phase == "processing":
            # Attach amount to data
            self.current_data["amount"] = self.amount
            
            log_event(self.clock.get_time(), "BPM1", "bill", {"amount": self.amount})
            
            self.hold_in("output", 0.0)
        elif self.phase == "output":
            self.current_data = None
            self.amount = 0
            self.hold_in("idle", float('inf'))

    def deltext(self, e):
        if self.phase == "idle":
            data = self.input["in"].values
            if data:
                req = list(data)[0]
                self.current_data = req
                self.amount = random.randint(0, 40)
                self.hold_in("processing", PROCESSING_DELAY)

    def exit(self):
        pass

class TPM(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out"))
        
        self.balance = 3000
        self.count = 0
        self.current_amount = 0
        self.hold_in("idle", float('inf'))

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        # TPM is a sink in this context, no output needed to other components
        pass

    def deltint(self):
        if self.phase == "processing":
            amount = self.current_amount
            if amount > self.balance:
                amount = self.balance
            
            self.balance -= amount
            self.count += 1
            
            log_event(self.clock.get_time(), "TPM1", "transaction", {
                "remaining": self.balance,
                "count": self.count
            })
            
            self.hold_in("output", 0.0)
        elif self.phase == "output":
            self.current_amount = 0
            self.hold_in("idle", float('inf'))

    def deltext(self, e):
        if self.phase == "idle":
            data = self.input["in"].values
            if data:
                req = list(data)[0]
                self.current_amount = req.get("amount", 0)
                self.hold_in("processing", PROCESSING_DELAY)

    def exit(self):
        pass

class IOBSSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Instantiate components
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
        
        # Couplings
        self.add_coupling(self.input_reader.output["out"], self.aam.input["in"])
        self.add_coupling(self.aam.output["out"], self.anv.input["in"])
        self.add_coupling(self.anv.output["out"], self.pv.input["in"])
        self.add_coupling(self.pv.output["out"], self.bpm.input["in"])
        self.add_coupling(self.bpm.output["out"], self.tpm.input["in"])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args()
    
    # Set seeds
    seed_val = time.time_ns()
    random.seed(seed_val)
    
    root = IOBSSystem(name="IOBS", parent=None)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(args.simulation_time)

if __name__ == "__main__":
    main()