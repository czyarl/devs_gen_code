import argparse
import sys
import json
import random
import time
import logging
from collections import deque

# xdevs imports
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Setup logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger("iobs_sim")

# --- Helper Functions ---

def parse_timestamp(ts_str):
    """Converts HH:MM:SS:mmm to float seconds."""
    parts = ts_str.split(':')
    h = int(parts[0])
    m = int(parts[1])
    s = int(parts[2])
    ms = int(parts[3])
    return h * 3600 + m * 60 + s + ms / 1000.0

def log_event(time, model, event, data):
    """Prints a JSONL event to stdout."""
    payload = {
        "time": time,
        "model": model,
        "event": event,
        "data": data
    }
    print(json.dumps(payload), file=sys.stdout, flush=True)

# --- Atomic Models ---

class InputReader(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_out_port(Port(dict, "out"))
        
        self.input_queue = deque()
        self.processing_time = 10.0

    def initialize(self):
        # Read all input from stdin immediately
        try:
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) != 3:
                    logger.warning(f"Skipping malformed line: {line}")
                    continue
                
                ts_str = parts[0]
                valid = int(parts[1])
                invalid = int(parts[2])
                
                ts = parse_timestamp(ts_str)
                
                # Store data and original timestamp
                self.input_queue.append({
                    "time": ts,
                    "valid": valid,
                    "invalid": invalid
                })
        except Exception as e:
            logger.error(f"Error reading input: {e}")

        # Start event
        log_event(0.0, "input_reader1", "start", {})
        
        # Schedule the first input processing at the timestamp of the first input.
        if self.input_queue:
            first_event_time = self.input_queue[0]["time"]
            self.hold_in("active", first_event_time)
        else:
            self.hold_in("passive", float('inf'))

    def lambdaf(self):
        if self.phase == "active" and self.input_queue:
            current_event = self.input_queue[0]
            log_event(self.time, "input_reader1", "input", {
                "valid": current_event["valid"], 
                "invalid": current_event["invalid"]
            })
            self.output["out"].add(current_event)

    def deltint(self):
        if self.phase == "active":
            # Remove the processed event
            if self.input_queue:
                self.input_queue.popleft()
            
            if self.input_queue:
                next_event_time = self.input_queue[0]["time"]
                # Calculate time until next event relative to current time
                time_to_next = next_event_time - self.time
                if time_to_next < 0:
                    time_to_next = 0
                
                self.hold_in("active", time_to_next)
            else:
                self.hold_in("passive", float('inf'))
        else:
            self.hold_in("passive", float('inf'))

    def deltext(self, e):
        # Input reader typically doesn't receive external input in this architecture
        pass

    def exit(self):
        pass

class AAM(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out_valid"))
        
        self.processing_time = 10.0

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "processing":
            # Check the state to decide what to output
            if hasattr(self, 'current_data'):
                if self.current_data["invalid"] == 1:
                    log_event(self.time, "AAM1", "logout", {})
                    # No output to next stage for logout
                else:
                    log_event(self.time, "AAM1", "account_generated", {})
                    self.output["out_valid"].add(self.current_data)

    def deltint(self):
        if self.phase == "processing":
            self.hold_in("idle", float('inf'))

    def deltext(self, e):
        if self.phase == "idle":
            # Receive input
            for val in self.input["in"].values:
                self.current_data = val
                # Processing delay is fixed
                self.hold_in("processing", self.processing_time)
        
    def exit(self):
        pass

class ANV(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out_pass"))
        
        self.processing_time = 10.0

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "processing":
            if hasattr(self, 'verification_result'):
                log_event(self.time, "ANV1", "verification", self.verification_result)
                
                if self.verification_result["pass"] == 1:
                    self.output["out_pass"].add(self.current_data)
                else:
                    # Fail - end processing (no output to next)
                    pass

    def deltint(self):
        if self.phase == "processing":
            self.hold_in("idle", float('inf'))

    def deltext(self, e):
        if self.phase == "idle":
            for val in self.input["in"].values:
                self.current_data = val
                # 50% chance pass
                if random.random() < 0.5:
                    self.verification_result = {"pass": 1, "fail": 0}
                else:
                    self.verification_result = {"pass": 0, "fail": 1}
                
                self.hold_in("processing", self.processing_time)

    def exit(self):
        pass

class PV(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out"))
        
        self.processing_time = 10.0

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "processing":
            if hasattr(self, 'attempts'):
                log_event(self.time, "PV1", "verification", {
                    "success": 1, 
                    "attempts": self.attempts
                })
                self.output["out"].add(self.current_data)

    def deltint(self):
        if self.phase == "processing":
            self.hold_in("idle", float('inf'))

    def deltext(self, e):
        if self.phase == "idle":
            for val in self.input["in"].values:
                self.current_data = val
                # "Performs random password check: 50% chance success per attempt."
                # "For simulation, the entity itself will try to log in until success."
                # We simulate the attempts count here, but the processing time is fixed at 10s
                # as per the "Each entities has a processing delay of 10 seconds" rule.
                
                attempts = 0
                while True:
                    attempts += 1
                    if random.random() < 0.5:
                        break
                
                self.attempts = attempts
                self.hold_in("processing", self.processing_time)

    def exit(self):
        pass

class BPM(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out"))
        
        self.processing_time = 10.0

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "processing":
            if hasattr(self, 'bill_amount'):
                log_event(self.time, "BPM1", "bill", {"amount": self.bill_amount})
                # Pass the amount along
                self.output["out"].add({"amount": self.bill_amount, "original_data": self.current_data})

    def deltint(self):
        if self.phase == "processing":
            self.hold_in("idle", float('inf'))

    def deltext(self, e):
        if self.phase == "idle":
            for val in self.input["in"].values:
                self.current_data = val
                # Need remaining balance. 
                # We use a global variable to share state between BPM and TPM 
                # since there is no feedback loop in the architecture.
                global current_balance
                amount = random.randint(0, 40)
                if amount > current_balance:
                    amount = current_balance
                
                self.bill_amount = amount
                self.hold_in("processing", self.processing_time)

    def exit(self):
        pass

class TPM(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out")) # To final output
        
        self.processing_time = 10.0
        self.balance = 3000
        self.transaction_count = 0
        
        # Update global balance for BPM to see
        global current_balance
        current_balance = self.balance

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.phase == "processing":
            if hasattr(self, 'last_transaction_amount'):
                log_event(self.time, "TPM1", "transaction", {
                    "remaining": self.balance,
                    "count": self.transaction_count
                })
                # Output final result
                self.output["out"].add({
                    "remaining": self.balance,
                    "count": self.transaction_count
                })

    def deltint(self):
        if self.phase == "processing":
            self.hold_in("idle", float('inf'))

    def deltext(self, e):
        if self.phase == "idle":
            for val in self.input["in"].values:
                amount = val.get("amount", 0)
                
                # Update state
                self.balance -= amount
                self.transaction_count += 1
                self.last_transaction_amount = amount
                
                # Update global balance for BPM
                global current_balance
                current_balance = self.balance
                
                self.hold_in("processing", self.processing_time)

    def exit(self):
        pass

# Global state for balance sharing (simplification for this specific architecture)
current_balance = 3000

# --- Coupled Model ---

class IOBSSystem(Coupled):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Instantiate components
        self.reader = InputReader("input_reader1", self)
        self.aam = AAM("AAM1", self)
        self.anv = ANV("ANV1", self)
        self.pv = PV("PV1", self)
        self.bpm = BPM("BPM1", self)
        self.tpm = TPM("TPM1", self)
        
        self.add_component(self.reader)
        self.add_component(self.aam)
        self.add_component(self.anv)
        self.add_component(self.pv)
        self.add_component(self.bpm)
        self.add_component(self.tpm)
        
        # Couplings
        # Input Reader -> AAM
        self.add_coupling(self.reader.output["out"], self.aam.input["in"])
        
        # AAM -> ANV (valid path)
        self.add_coupling(self.aam.output["out_valid"], self.anv.input["in"])
        
        # ANV -> PV (pass path)
        self.add_coupling(self.anv.output["out_pass"], self.pv.input["in"])
        
        # PV -> BPM
        self.add_coupling(self.pv.output["out"], self.bpm.input["in"])
        
        # BPM -> TPM
        self.add_coupling(self.bpm.output["out"], self.tpm.input["in"])
        
        # TPM -> Output (EOC)
        self.add_out_port(Port(dict, "out"))
        self.add_coupling(self.tpm.output["out"], self.output["out"])

# --- Main Entry Point ---

def main():
    parser = argparse.ArgumentParser(description="Internet Online Banking System Simulation")
    parser.add_argument("--simulation_time", type=float, default=1000000.0, help="Total simulation time in seconds")
    args = parser.parse_args()
    
    # Seed random
    seed_val = time.time_ns()
    random.seed(seed_val)
    # numpy is available but not strictly used if random is sufficient, 
    # but prompt mentioned it. Let's seed it too just in case.
    try:
        import numpy
        numpy.random.seed(seed_val % (2**32 - 1))
    except ImportError:
        pass

    logger.info(f"Starting simulation with seed {seed_val}")
    
    # Build System
    root = IOBSSystem("iobs_system", None)
    
    # Setup Coordinator
    # SimulationClock(0) means start at time 0
    coord = Coordinator(root, clock=SimulationClock(0))
    
    # Initialize
    coord.initialize()
    
    # Simulate
    try:
        coord.simulate_time(args.simulation_time)
    except Exception as e:
        logger.error(f"Simulation error: {e}")
        import traceback
        traceback.print_exc(file=sys.stderr)
    
    logger.info("Simulation finished.")

if __name__ == "__main__":
    main()