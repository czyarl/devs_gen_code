#!/usr/bin/env python3
"""
Internet Online Banking System (IOBS) - Discrete Event Simulation
"""

import argparse
import sys
import json
import logging
import time
import random
import simpy

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)

class InputReader:
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
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
                
            try:
                # Parse timestamp and flags
                parts = line.split()
                if len(parts) != 3:
                    logging.warning(f"Invalid input line: {line}")
                    continue
                    
                timestamp_str, valid_str, invalid_str = parts
                valid = int(valid_str)
                invalid = int(invalid_str)
                
                # Parse timestamp
                time_parts = timestamp_str.split(':')
                hours, minutes, seconds, milliseconds = map(int, time_parts)
                total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
                
                # Emit input event at the timestamp
                yield self.env.timeout(total_seconds)
                print(json.dumps({
                    "time": total_seconds,
                    "model": "input_reader1",
                    "event": "input",
                    "data": {
                        "valid": valid,
                        "invalid": invalid
                    }
                }))
                
                # Forward to AAM
                self.aam.receive_input(valid, invalid, total_seconds)
                
            except Exception as e:
                logging.error(f"Error processing input line '{line}': {e}")
                
        # Wait for all events to complete
        yield self.env.timeout(1000000)  # Wait for a long time to ensure completion

class AAM:
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
        self.process = env.process(self.run())
        
    def run(self):
        # Wait for input
        while True:
            yield self.env.timeout(1000000)  # Wait indefinitely for input
            
    def receive_input(self, valid, invalid, timestamp):
        # AAM processing delay: 10 seconds
        self.env.process(self.process_input(valid, invalid, timestamp))
        
    def process_input(self, valid, invalid, timestamp):
        yield self.env.timeout(10)  # 10 second delay
        
        if valid == 1 and invalid == 0:
            # Valid login - forward to ANV
            print(json.dumps({
                "time": timestamp + 10,
                "model": "AAM1",
                "event": "account_generated",
                "data": {}
            }))
            self.anv.receive_account(timestamp + 10)
        elif valid == 1 and invalid == 1:
            # Invalid login - trigger logout
            print(json.dumps({
                "time": timestamp + 10,
                "model": "AAM1",
                "event": "logout",
                "data": {}
            }))

class ANV:
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
        self.process = env.process(self.run())
        
    def run(self):
        # Wait for input
        while True:
            yield self.env.timeout(1000000)  # Wait indefinitely for input
            
    def receive_account(self, timestamp):
        # ANV processing delay: 10 seconds
        self.env.process(self.process_account(timestamp))
        
    def process_account(self, timestamp):
        yield self.env.timeout(10)  # 10 second delay
        
        # 50% chance pass, 50% chance fail
        result = random.choice([0, 1])  # 0 = fail, 1 = pass
        
        print(json.dumps({
            "time": timestamp + 10,
            "model": "ANV1",
            "event": "verification",
            "data": {
                "pass": result,
                "fail": 1 - result
            }
        }))
        
        if result == 1:
            # Pass - forward to PV
            self.pv.receive_verification(timestamp + 20)
        # If fail, processing ends here

class PV:
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm
        self.process = env.process(self.run())
        
    def run(self):
        # Wait for input
        while True:
            yield self.env.timeout(1000000)  # Wait indefinitely for input
            
    def receive_verification(self, timestamp):
        # PV processing delay: 10 seconds
        self.env.process(self.process_verification(timestamp))
        
    def process_verification(self, timestamp):
        yield self.env.timeout(10)  # 10 second delay
        
        # 50% chance success per attempt
        attempts = 0
        success = False
        
        while not success:
            attempts += 1
            success = random.choice([True, False])
            
        print(json.dumps({
            "time": timestamp + 10,
            "model": "PV1",
            "event": "verification",
            "data": {
                "success": 1,
                "attempts": attempts
            }
        }))
        
        # Forward to BPM
        self.bpm.receive_bill(timestamp + 20)

class BPM:
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
        self.process = env.process(self.run())
        self.balance = 3000
        self.transaction_count = 0
        
    def run(self):
        # Wait for input
        while True:
            yield self.env.timeout(1000000)  # Wait indefinitely for input
            
    def receive_bill(self, timestamp):
        # BPM processing delay: 10 seconds
        self.env.process(self.process_bill(timestamp))
        
    def process_bill(self, timestamp):
        yield self.env.timeout(10)  # 10 second delay
        
        # Generate random bill amount between 0 and 40
        amount = random.randint(0, 40)
        
        # Make sure it doesn't exceed remaining balance
        if amount > self.balance:
            amount = self.balance
            
        print(json.dumps({
            "time": timestamp + 10,
            "model": "BPM1",
            "event": "bill",
            "data": {
                "amount": amount
            }
        }))
        
        # Forward to TPM
        self.tpm.receive_transaction(timestamp + 20, amount)

class TPM:
    def __init__(self, env):
        self.env = env
        self.balance = 3000
        self.transaction_count = 0
        self.process = env.process(self.run())
        
    def run(self):
        # Wait for input
        while True:
            yield self.env.timeout(1000000)  # Wait indefinitely for input
            
    def receive_transaction(self, timestamp, amount):
        # TPM processing delay: 10 seconds
        self.env.process(self.process_transaction(timestamp, amount))
        
    def process_transaction(self, timestamp, amount):
        yield self.env.timeout(10)  # 10 second delay
        
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
    parser.add_argument('--simulation_time', type=float, default=1000000.0, help='Total simulation time in seconds')
    
    args = parser.parse_args()
    
    # Set random seed using system time
    random.seed(time.time_ns())
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create components
    anv = ANV(env, None)  # Will be updated later
    pv = PV(env, None)    # Will be updated later
    bpm = BPM(env, None)  # Will be updated later
    tpm = TPM(env)
    
    # Create AAM with reference to ANV
    aam = AAM(env, anv)
    
    # Update references
    anv.pv = pv
    pv.bpm = bpm
    bpm.tpm = tpm
    
    # Create InputReader with reference to AAM
    input_reader = InputReader(env, aam)
    
    # Run simulation
    env.run(until=args.simulation_time)
    
    logging.info("Simulation completed")

if __name__ == "__main__":
    main()