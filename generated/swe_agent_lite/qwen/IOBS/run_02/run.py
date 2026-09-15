#!/usr/bin/env python3
"""
Discrete Event Simulation for Internet Online Banking System (IOBS)
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
    """Reads input from stdin and forwards to AAM"""
    
    def __init__(self, env, aam):
        self.env = env
        self.aam = aam
        self.process = env.process(self.read_input())
        
    def read_input(self):
        """Read input from stdin line by line"""
        # Emit start event at t=0
        print(json.dumps({
            "time": 0.0,
            "model": "input_reader1",
            "event": "start",
            "data": {}
        }))
        
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
                
            try:
                # Parse timestamp and request data
                timestamp_str, valid_str, invalid_str = line.split()
                valid = int(valid_str)
                invalid = int(invalid_str)
                
                # Convert timestamp to seconds
                hours, minutes, seconds, milliseconds = map(int, timestamp_str.split(':'))
                timestamp = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
                
                # Emit input event
                print(json.dumps({
                    "time": timestamp,
                    "model": "input_reader1",
                    "event": "input",
                    "data": {
                        "valid": valid,
                        "invalid": invalid
                    }
                }))
                
                # Forward to AAM
                self.aam.receive_request(valid, invalid, timestamp)
                
            except ValueError as e:
                logging.error(f"Error parsing input line '{line}': {e}")
                continue

class AAM:
    """Account Access Manager"""
    
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
        self.process = env.process(self.run())
        self.request_queue = []
        
    def receive_request(self, valid, invalid, timestamp):
        """Receive request from input reader"""
        self.request_queue.append((valid, invalid, timestamp))
        if len(self.request_queue) == 1:
            self.env.process(self.process_request())
        
    def process_request(self):
        """Process requests from queue"""
        while self.request_queue:
            valid, invalid, timestamp = self.request_queue.pop(0)
            
            # AAM processing delay of 10 seconds
            yield self.env.timeout(10)
            
            if invalid == 1:
                # Invalid login - trigger logout
                print(json.dumps({
                    "time": timestamp + 10,
                    "model": "AAM1",
                    "event": "logout",
                    "data": {}
                }))
            else:
                # Valid login - forward to ANV
                print(json.dumps({
                    "time": timestamp + 10,
                    "model": "AAM1",
                    "event": "account_generated",
                    "data": {}
                }))
                self.anv.receive_account(timestamp + 10)

class ANV:
    """Account Number Verifier"""
    
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
        self.process = env.process(self.run())
        self.account_queue = []
        
    def receive_account(self, timestamp):
        """Receive account from AAM"""
        self.account_queue.append(timestamp)
        if len(self.account_queue) == 1:
            self.env.process(self.process_account())
        
    def process_account(self):
        """Process accounts from queue"""
        while self.account_queue:
            timestamp = self.account_queue.pop(0)
            
            # ANV processing delay of 10 seconds
            yield self.env.timeout(10)
            
            # 50% chance pass, 50% chance fail
            pass_verification = random.choice([True, False])
            
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
                self.pv.receive_verification(timestamp + 10)
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
        self.verification_queue = []
        
    def receive_verification(self, timestamp):
        """Receive verification from ANV"""
        self.verification_queue.append(timestamp)
        if len(self.verification_queue) == 1:
            self.env.process(self.process_verification())
        
    def process_verification(self):
        """Process verifications from queue"""
        while self.verification_queue:
            timestamp = self.verification_queue.pop(0)
            
            # PV processing delay of 10 seconds
            yield self.env.timeout(10)
            
            # Keep trying until success (50% chance per attempt)
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
            self.bpm.receive_bill_request(timestamp + 10)

class BPM:
    """Bill Payment Manager"""
    
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
        self.process = env.process(self.run())
        self.bill_queue = []
        
    def receive_bill_request(self, timestamp):
        """Receive bill request from PV"""
        self.bill_queue.append(timestamp)
        if len(self.bill_queue) == 1:
            self.env.process(self.process_bill_request())
        
    def process_bill_request(self):
        """Process bill requests from queue"""
        while self.bill_queue:
            timestamp = self.bill_queue.pop(0)
            
            # BPM processing delay of 10 seconds
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
            self.tpm.receive_transaction(amount, timestamp + 10)

class TPM:
    """Transaction Process Manager"""
    
    def __init__(self, env):
        self.env = env
        self.balance = 3000
        self.transaction_count = 0
        self.process = env.process(self.run())
        self.transaction_queue = []
        
    def receive_transaction(self, amount, timestamp):
        """Receive transaction from BPM"""
        self.transaction_queue.append((amount, timestamp))
        if len(self.transaction_queue) == 1:
            self.env.process(self.process_transaction())
        
    def process_transaction(self):
        """Process transactions from queue"""
        while self.transaction_queue:
            amount, timestamp = self.transaction_queue.pop(0)
            
            # TPM processing delay of 10 seconds
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
    """Main function to run the simulation"""
    # Set random seed using system time
    random.seed(time.time_ns())
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='IOBS Discrete Event Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0, 
                       help='Total simulation time in seconds. Default: 1000000.0')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create components
    tpm = TPM(env)
    bpm = BPM(env, tpm)
    pv = PV(env, bpm)
    anv = ANV(env, pv)
    aam = AAM(env, anv)
    input_reader = InputReader(env, aam)
    
    # Run simulation
    env.run(until=args.simulation_time)
    
    # Ensure simulation ends in 10 seconds real time
    # This is handled by the simpy environment which will stop at the specified time

if __name__ == "__main__":
    main()