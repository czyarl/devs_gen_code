import argparse
import sys
import json
import logging
import random
import time
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Set random seed using system time
random.seed(time.time_ns())
import numpy
numpy.random.seed(time.time_ns() % (2**32 - 1))

# Constants
PROCESSING_DELAY = 10.0  # 10 seconds delay for each entity
INITIAL_BALANCE = 3000

# Helper function to parse timestamp string to seconds
def parse_timestamp(timestamp_str):
    """Convert HH:MM:SS:mmm to seconds"""
    parts = timestamp_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0

class InputReader1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.input_port = self.add_in_port(Port(str, "input"))
        self.output_port = self.add_out_port(Port(dict, "output"))
        self.requests = []
        self.current_index = 0
        self.time_offset = 0.0
        self.has_started = False

    def initialize(self):
        # Print start event at t=0
        print(json.dumps({"time": 0.0, "model": "input_reader1", "event": "start", "data": {}}), file=sys.stdout, flush=True)
        self.has_started = True
        
        # Read all input from stdin
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            timestamp_str = parts[0]
            valid = int(parts[1])
            invalid = int(parts[2])
            sim_time = parse_timestamp(timestamp_str)
            self.requests.append((sim_time, valid, invalid))
        
        # Sort requests by timestamp
        self.requests.sort(key=lambda x: x[0])
        
        # If we have requests, schedule the first one
        if self.requests:
            first_time = self.requests[0][0]
            self.hold_in("waiting", first_time)
        else:
            # No requests, finish immediately
            self.hold_in("finished", float('inf'))

    def lambdaf(self):
        if self.current_index < len(self.requests):
            sim_time, valid, invalid = self.requests[self.current_index]
            # Output the input event
            print(json.dumps({
                "time": sim_time, 
                "model": "input_reader1", 
                "event": "input", 
                "data": {"valid": valid, "invalid": invalid}
            }), file=sys.stdout, flush=True)
            
            # Send to AAM
            self.output_port.add({"valid": valid, "invalid": invalid, "timestamp": sim_time})

    def deltint(self):
        # Internal transition: move to next request
        self.current_index += 1
        if self.current_index < len(self.requests):
            next_time = self.requests[self.current_index][0]
            self.hold_in("waiting", next_time)
        else:
            # No more requests, finish simulation
            self.hold_in("finished", float('inf'))

    def deltext(self, e):
        # External transition: should not receive external inputs
        pass

    def exit(self):
        # Cleanup
        pass


class AAM1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.input_port = self.add_in_port(Port(dict, "input"))
        self.output_port = self.add_out_port(Port(dict, "output"))
        self.current_request = None
        self.processing = False

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.current_request:
            if self.current_request["invalid"] == 1:
                # Invalid login - trigger logout
                print(json.dumps({
                    "time": self.time, 
                    "model": "AAM1", 
                    "event": "logout", 
                    "data": {}
                }), file=sys.stdout, flush=True)
            else:
                # Valid login - generate account
                print(json.dumps({
                    "time": self.time, 
                    "model": "AAM1", 
                    "event": "account_generated", 
                    "data": {}
                }), file=sys.stdout, flush=True)
                # Forward to ANV
                self.output_port.add({"timestamp": self.current_request["timestamp"]})

    def deltint(self):
        # After processing delay, we're done with this request
        self.current_request = None
        self.hold_in("idle", float('inf'))

    def deltext(self, e):
        # Process incoming request
        for msg in self.input_port.values:
            self.current_request = msg
            # Process with delay
            self.hold_in("processing", PROCESSING_DELAY)

    def exit(self):
        pass


class ANV1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.input_port = self.add_in_port(Port(dict, "input"))
        self.output_port = self.add_out_port(Port(dict, "output"))
        self.current_request = None

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.current_request:
            # 50% chance pass, 50% chance fail
            pass_result = random.choice([True, False])
            pass_flag = 1 if pass_result else 0
            fail_flag = 0 if pass_result else 1
            
            print(json.dumps({
                "time": self.time, 
                "model": "ANV1", 
                "event": "verification", 
                "data": {"pass": pass_flag, "fail": fail_flag}
            }), file=sys.stdout, flush=True)
            
            if pass_result:
                # Forward to PV
                self.output_port.add({"timestamp": self.current_request["timestamp"]})

    def deltint(self):
        self.current_request = None
        self.hold_in("idle", float('inf'))

    def deltext(self, e):
        for msg in self.input_port.values:
            self.current_request = msg
            self.hold_in("verifying", PROCESSING_DELAY)

    def exit(self):
        pass


class PV1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.input_port = self.add_in_port(Port(dict, "input"))
        self.output_port = self.add_out_port(Port(dict, "output"))
        self.current_request = None
        self.attempts = 0

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.current_request:
            # PV will keep trying until success (guaranteed success eventually)
            print(json.dumps({
                "time": self.time, 
                "model": "PV1", 
                "event": "verification", 
                "data": {"success": 1, "attempts": self.attempts}
            }), file=sys.stdout, flush=True)
            
            # Forward to BPM
            self.output_port.add({"timestamp": self.current_request["timestamp"]})

    def deltint(self):
        self.current_request = None
        self.attempts = 0
        self.hold_in("idle", float('inf'))

    def deltext(self, e):
        for msg in self.input_port.values:
            self.current_request = msg
            # Keep trying until success - simulate multiple attempts within the delay
            # We'll simulate 1-5 attempts (random) but guarantee success on last
            self.attempts = random.randint(1, 5)
            # Since we guarantee success eventually, we'll use the last attempt as success
            self.hold_in("verifying", PROCESSING_DELAY)

    def exit(self):
        pass


class BPM1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.input_port = self.add_in_port(Port(dict, "input"))
        self.output_port = self.add_out_port(Port(dict, "output"))
        self.current_request = None
        self.remaining_balance = INITIAL_BALANCE

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.current_request:
            # Generate random bill amount between 0 and 40, constrained by remaining balance
            max_amount = min(40, self.remaining_balance)
            amount = random.randint(0, max_amount)
            
            print(json.dumps({
                "time": self.time, 
                "model": "BPM1", 
                "event": "bill", 
                "data": {"amount": amount}
            }), file=sys.stdout, flush=True)
            
            # Forward to TPM with amount
            self.output_port.add({"amount": amount, "timestamp": self.current_request["timestamp"]})

    def deltint(self):
        self.current_request = None
        self.hold_in("idle", float('inf'))

    def deltext(self, e):
        for msg in self.input_port.values:
            self.current_request = msg
            self.hold_in("generating", PROCESSING_DELAY)

    def exit(self):
        pass


class TPM1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.input_port = self.add_in_port(Port(dict, "input"))
        self.output_port = self.add_out_port(Port(dict, "output"))
        self.current_request = None
        self.remaining_balance = INITIAL_BALANCE
        self.transaction_count = 0

    def initialize(self):
        self.hold_in("idle", float('inf'))

    def lambdaf(self):
        if self.current_request:
            amount = self.current_request["amount"]
            self.remaining_balance -= amount
            self.transaction_count += 1
            
            print(json.dumps({
                "time": self.time, 
                "model": "TPM1", 
                "event": "transaction", 
                "data": {"remaining": self.remaining_balance, "count": self.transaction_count}
            }), file=sys.stdout, flush=True)

    def deltint(self):
        self.current_request = None
        self.hold_in("idle", float('inf'))

    def deltext(self, e):
        for msg in self.input_port.values:
            self.current_request = msg
            self.hold_in("processing", PROCESSING_DELAY)

    def exit(self):
        pass


class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, simulation_time: float):
        super().__init__(name)
        self.parent = parent
        self.simulation_time = simulation_time
        
        # Instantiate components
        self.input_reader = InputReader1("input_reader1", self)
        self.aam = AAM1("AAM1", self)
        self.anv = ANV1("ANV1", self)
        self.pv = PV1("PV1", self)
        self.bpm = BPM1("BPM1", self)
        self.tpm = TPM1("TPM1", self)
        
        # Add components
        self.add_component(self.input_reader)
        self.add_component(self.aam)
        self.add_component(self.anv)
        self.add_component(self.pv)
        self.add_component(self.bpm)
        self.add_component(self.tpm)
        
        # Define couplings
        # input_reader -> AAM
        self.add_coupling(self.input_reader.output_port, self.aam.input_port)
        # AAM -> ANV (only for valid logins)
        self.add_coupling(self.aam.output_port, self.anv.input_port)
        # ANV -> PV (only for pass)
        self.add_coupling(self.anv.output_port, self.pv.input_port)
        # PV -> BPM
        self.add_coupling(self.pv.output_port, self.bpm.input_port)
        # BPM -> TPM
        self.add_coupling(self.bpm.output_port, self.tpm.input_port)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args()
    
    # Create system
    root = System("system", None, args.simulation_time)
    
    # Create coordinator and simulate
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    
    # Set a timeout of 10 seconds real time to ensure simulation ends
    # We'll use the simulation_time for the simulation, but limit real time to 10s
    import threading
    import time
    
    def simulate_with_timeout():
        try:
            coord.simulate_time(args.simulation_time)
        except Exception as e:
            print(f"Simulation error: {e}", file=sys.stderr)
    
    thread = threading.Thread(target=simulate_with_timeout)
    thread.daemon = True
    thread.start()
    
    # Wait for up to 10 seconds for simulation to complete
    thread.join(timeout=10.0)
    
    # If thread is still alive, we force exit
    if thread.is_alive():
        print("Simulation timed out after 10 seconds real time.", file=sys.stderr)
    
    # Ensure all output is flushed
    sys.stdout.flush()
    sys.stderr.flush()


if __name__ == "__main__":
    main()