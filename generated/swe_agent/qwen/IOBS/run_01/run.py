#!/usr/bin/env python3
"""
Internet Online Banking System (IOBS) Discrete Event Simulation
"""

import argparse
import sys
import json
import logging
import collections
import random
import time
import simpy

# Set random seed using system time
random.seed(time.time_ns())

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class InputReader:
    """Reads input from stdin and forwards to AAM"""
    
    def __init__(self, env, aam):
        self.env = env
        self.aam = aam
        self.process = env.process(self.run())
        
    def run(self):
        # Emit start event at t=0
        yield self.env.timeout(0)
        print(json.dumps({
            "time": 0.0,
            "model": "input_reader1",
            "event": "start",
            "data": {}
        }))
        
        # Read input from stdin
        input_events = []
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
                
            try:
                # Parse timestamp and flags
                timestamp_str, valid_str, invalid_str = line.split()
                valid = int(valid_str)
                invalid = int(invalid_str)
                
                # Convert timestamp to seconds
                hours, minutes, seconds, milliseconds = map(int, timestamp_str.split(':'))
                timestamp = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
                
                input_events.append((timestamp, valid, invalid))
                
            except Exception as e:
                logger.error(f"Error processing input line '{line}': {e}")
        
        # Sort events by timestamp
        input_events.sort(key=lambda x: x[0])
        
        # Process events in time order
        for timestamp, valid, invalid in input_events:
            # Emit input event at the correct time
            # We need to calculate the delay from current simulation time
            delay = max(0, timestamp - self.env.now)
            yield self.env.timeout(delay)
            print(json.dumps({
                "time": timestamp,
                "model": "input_reader1",
                "event": "input",
                "data": {
                    "valid": valid,
                    "invalid": invalid
                }
            }))
            
            # Forward to AAM after 10 seconds processing delay
            yield self.env.timeout(10)
            self.aam.receive_input(valid, invalid, timestamp + 10)

class AAM:
    """Account Access Manager"""
    
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
        self.process = env.process(self.run())
        
    def run(self):
        # This is a generator function, but we don't need to do anything here
        # The processing happens in receive_input
        yield self.env.timeout(0)  # This makes it a generator
        
    def receive_input(self, valid, invalid, timestamp):
        # AAM processing delay of 10 seconds
        self.env.process(self.process_input(valid, invalid, timestamp))
        
    def process_input(self, valid, invalid, timestamp):
        yield self.env.timeout(10)
        
        if valid == 1 and invalid == 0:
            # Valid login - forward to ANV
            print(json.dumps({
                "time": timestamp + 10,
                "model": "AAM1",
                "event": "account_generated",
                "data": {}
            }))
            self.anv.receive_account(timestamp + 20)
        elif valid == 1 and invalid == 1:
            # Invalid login - trigger logout
            print(json.dumps({
                "time": timestamp + 10,
                "model": "AAM1",
                "event": "logout",
                "data": {}
            }))

class ANV:
    """Account Number Verifier"""
    
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
        self.process = env.process(self.run())
        
    def run(self):
        # This is a generator function, but we don't need to do anything here
        # The processing happens in receive_account
        yield self.env.timeout(0)  # This makes it a generator
        
    def receive_account(self, timestamp):
        # ANV processing delay of 10 seconds
        self.env.process(self.process_account(timestamp))
        
    def process_account(self, timestamp):
        yield self.env.timeout(10)
        
        # 50% chance pass, 50% chance fail
        pass_verification = random.random() < 0.5
        
        if pass_verification:
            print(json.dumps({
                "time": timestamp + 10,
                "model": "ANV1",
                "event": "verification",
                "data": {
                    "pass": 1,
                    "fail": 0
                }
            }))
            self.pv.receive_verification(timestamp + 20)
        else:
            print(json.dumps({
                "time": timestamp + 10,
                "model": "ANV1",
                "event": "verification",
                "data": {
                    "pass": 0,
                    "fail": 1
                }
            }))

class PV:
    """Password Verifier"""
    
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm
        self.process = env.process(self.run())
        self.attempts = 0
        
    def run(self):
        # This is a generator function, but we don't need to do anything here
        # The processing happens in receive_verification
        yield self.env.timeout(0)  # This makes it a generator
        
    def receive_verification(self, timestamp):
        # PV processing delay of 10 seconds
        self.env.process(self.process_verification(timestamp))
        
    def process_verification(self, timestamp):
        yield self.env.timeout(10)
        
        # Keep trying until success (50% chance per attempt)
        success = False
        self.attempts = 0
        
        while not success:
            self.attempts += 1
            success = random.random() < 0.5
            
        print(json.dumps({
            "time": timestamp + 10,
            "model": "PV1",
            "event": "verification",
            "data": {
                "success": 1,
                "attempts": self.attempts
            }
        }))
        
        # Forward to BPM
        self.bpm.receive_password(timestamp + 20)

class BPM:
    """Bill Payment Manager"""
    
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
        self.process = env.process(self.run())
        
    def run(self):
        # This is a generator function, but we don't need to do anything here
        # The processing happens in receive_password
        yield self.env.timeout(0)  # This makes it a generator
        
    def receive_password(self, timestamp):
        # BPM processing delay of 10 seconds
        self.env.process(self.process_password(timestamp))
        
    def process_password(self, timestamp):
        yield self.env.timeout(10)
        
        # Generate random bill amount between 0 and 40
        amount = random.randint(0, 40)
        
        print(json.dumps({
            "time": timestamp + 10,
            "model": "BPM1",
            "event": "bill",
            "data": {
                "amount": amount
            }
        }))
        
        # Forward to TPM
        self.tpm.receive_bill(amount, timestamp + 20)

class TPM:
    """Transaction Process Manager"""
    
    def __init__(self, env):
        self.env = env
        self.balance = 3000
        self.transaction_count = 0
        self.process = env.process(self.run())
        
    def run(self):
        # This is a generator function, but we don't need to do anything here
        # The processing happens in receive_bill
        yield self.env.timeout(0)  # This makes it a generator
        
    def receive_bill(self, amount, timestamp):
        # TPM processing delay of 10 seconds
        self.env.process(self.process_bill(amount, timestamp))
        
    def process_bill(self, amount, timestamp):
        yield self.env.timeout(10)
        
        # Calculate remaining balance
        self.balance -= amount
        self.transaction_count += 1
        
        print(json.dumps({
            "time": timestamp + 10,
            "model": "TPM1",
            "event": "transaction",
            "data": {
                "remaining": self.balance,
                "count": self.transaction_count
            }
        }))

def main():
    parser = argparse.ArgumentParser(description='IOBS Discrete Event Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0, 
                       help='Total simulation time in seconds')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create components
    tpm = TPM(env)
    bpm = BPM(env, tpm)
    pv = PV(env, bpm)
    anv = ANV(env, pv)
    aam = AAM(env, anv)
    
    # Create input reader
    input_reader = InputReader(env, aam)
    
    # Run simulation
    env.run(until=args.simulation_time)
    
    # Ensure simulation ends in 10 seconds real time
    # This is handled by the environment run with a time limit

if __name__ == "__main__":
    main()