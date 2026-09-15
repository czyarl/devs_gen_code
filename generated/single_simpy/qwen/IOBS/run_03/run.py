```python_code
import argparse
import sys
import json
import logging
import random
import time
from collections import defaultdict

import simpy

# Set random seed based on system time
random.seed(time.time_ns())

class EventLogger:
    def __init__(self):
        self.events = []
    
    def log(self, time, model, event, data):
        event_obj = {
            "time": time,
            "model": model,
            "event": event,
            "data": data
        }
        self.events.append(event_obj)
        print(json.dumps(event_obj), file=sys.stdout)

class InputReader:
    def __init__(self, env, event_logger, aam):
        self.env = env
        self.event_logger = event_logger
        self.aam = aam
        self.process = env.process(self.run())
    
    def run(self):
        # Log start event
        self.event_logger.log(0.0, "input_reader1", "start", {})
        
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split()
            if len(parts) != 3:
                continue
                
            timestamp_str, valid_str, invalid_str = parts
            valid = int(valid_str)
            invalid = int(invalid_str)
            
            # Parse timestamp
            try:
                h, m, s, ms = map(int, timestamp_str.split(":"))
                time_seconds = h * 3600 + m * 60 + s + ms / 1000.0
            except ValueError:
                continue
            
            # Schedule input event at the parsed time
            yield self.env.timeout(time_seconds)
            self.event_logger.log(time_seconds, "input_reader1", "input", {"valid": valid, "invalid": invalid})
            self.aam.receive_input(valid, invalid, time_seconds)

class AAM:
    def __init__(self, env, event_logger, anv):
        self.env = env
        self.event_logger = event_logger
        self.anv = anv
        self.process = env.process(self.run())
    
    def receive_input(self, valid, invalid, time):
        if valid == 1 and invalid == 0:
            # Valid login, forward to ANV
            self.event_logger.log(time + 10.0, "AAM1", "account_generated", {})
            # Schedule ANV processing after 10 seconds
            self.env.process(self.anv.process_account(time + 10.0))
        elif valid == 1 and invalid == 1:
            # Invalid login, trigger logout
            self.event_logger.log(time + 10.0, "AAM1", "logout", {})
    
    def run(self):
        # AAM doesn't do anything special in its run method
        yield self.env.timeout(1000000.0)  # Never ends

class ANV:
    def __init__(self, env, event_logger, pv):
        self.env = env
        self.event_logger = event_logger
        self.pv = pv
        self.process = env.process(self.run())
    
    def process_account(self, time):
        # 50% chance of passing
        pass_verification = random.random() < 0.5
        if pass_verification:
            self.event_logger.log(time + 10.0, "ANV1", "verification", {"pass": 1, "fail": 0})
            # Forward to PV
            self.env.process(self.pv.process_verification(time + 10.0))
        else:
            self.event_logger.log(time + 10.0, "ANV1", "verification", {"pass": 0, "fail": 1})
            # End processing
    
    def run(self):
        # ANV doesn't do anything special in its run method
        yield self.env.timeout(1000000.0)  # Never ends

class PV:
    def __init__(self, env, event_logger, bpm):
        self.env = env
        self.event_logger = event_logger
        self.bpm = bpm
        self.process = env.process(self.run())
    
    def process_verification(self, time):
        attempts = 0
        success = False
        while not success:
            attempts += 1
            # 50% chance of success per attempt
            if random.random() < 0.5:
                success = True
                break
            # Wait for another attempt (10 seconds delay)
            yield self.env.timeout(10.0)
        
        if success:
            self.event_logger.log(time + 10.0, "PV1", "verification", {"success": 1, "attempts": attempts})
            # Forward to BPM
            self.env.process(self.bpm.generate_bill(time + 10.0))
    
    def run(self):
        # PV doesn't do anything special in its run method
        yield self.env.timeout(1000000.0)  # Never ends

class BPM:
    def __init__(self, env, event_logger, tpm):
        self.env = env
        self.event_logger = event_logger
        self.tpm = tpm
        self.process = env.process(self.run())
    
    def generate_bill(self, time):
        # Generate random bill amount between 0 and 40
        amount = random.randint(0, 40)
        self.event_logger.log(time + 10.0, "BPM1", "bill", {"amount": amount})
        # Forward to TPM
        self.env.process(self.tpm.process_transaction(time + 10.0, amount))
    
    def run(self):
        # BPM doesn't do anything special in its run method
        yield self.env.timeout(1000000.0)  # Never ends

class TPM:
    def __init__(self, env, event_logger):
        self.env = env
        self.event_logger = event_logger
        self.balance = 3000
        self.transaction_count = 0
        self.process = env.process(self.run())
    
    def process_transaction(self, time, amount):
        # Deduct amount from balance
        self.balance -= amount
        self.transaction_count += 1
        self.event_logger.log(time + 10.0, "TPM1", "transaction", {"remaining": self.balance, "count": self.transaction_count})
    
    def run(self):
        # TPM doesn't do anything special in its run method
        yield self.env.timeout(1000000.0)  # Never ends

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulation_time', type=float, default=1000000.0)
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create event logger
    event_logger = EventLogger()
    
    # Create components
    aam = AAM(env, event_logger, None)  # Will be updated later
    anv = ANV(env, event_logger, None)  # Will be updated later
    pv = PV(env, event_logger, None)    # Will be updated later
    bpm = BPM(env, event_logger, None)  # Will be updated later
    tpm = TPM(env, event_logger)
    
    # Set up connections
    aam.anv = anv
    anv.pv = pv
    pv.bpm = bpm
    bpm.tpm = tpm
    
    # Create input reader
    input_reader = InputReader(env, event_logger, aam)
    
    # Run simulation
    env.run(until=args.simulation_time)

if __name__ == "__main__":
    main()
</python_code>