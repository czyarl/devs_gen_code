#!/usr/bin/env python3
"""
Internet Online Banking System (IOBS) Discrete Event Simulation
"""
import argparse
import sys
import json
import logging
import random
import time
import simpy

# Set seed for reproducibility using system time
random.seed(time.time_ns())

# Global variables for simulation
SIMULATION_TIME = 1000000.0  # Default simulation time
INITIAL_BALANCE = 3000

def parse_timestamp(timestamp_str):
    """Parse timestamp string HH:MM:SS:mmm into seconds"""
    h, m, s, ms = map(int, timestamp_str.split(':'))
    return h * 3600 + m * 60 + s + ms / 1000.0

class InputReader:
    """Reads input from stdin and forwards to AAM"""
    
    def __init__(self, env, aam):
        self.env = env
        self.aam = aam
        self.process = env.process(self.run())
        
    def run(self):
        # Emit start event at t=0
        print(json.dumps({
            "time": 0.0,
            "model": "input_reader1",
            "event": "start",
            "data": {}
        }), file=sys.stdout)
        
        # Read input from stdin
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
                
            try:
                timestamp_str, valid_str, invalid_str = line.split()
                timestamp = parse_timestamp(timestamp_str)
                valid = int(valid_str)
                invalid = int(invalid_str)
                
                # Forward to AAM immediately (no delay for input processing)
                self.aam.receive_input(valid, invalid, timestamp)
                
            except Exception as e:
                print(f"Error processing input line: {line}", file=sys.stderr)
                continue

class AAM:
    """Account Access Manager"""
    
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
        self.process = env.process(self.run())
        
    def receive_input(self, valid, invalid, timestamp):
        """Receive input from input_reader1"""
        # Schedule processing after 10 seconds delay
        self.env.process(self.process_input(valid, invalid, timestamp))
        
    def process_input(self, valid, invalid, timestamp):
        """Process the input after 10 seconds delay"""
        yield self.env.timeout(10.0)
        
        if valid == 1 and invalid == 0:
            # Valid login - forward to ANV
            print(json.dumps({
                "time": timestamp + 10.0,
                "model": "AAM1",
                "event": "account_generated",
                "data": {}
            }), file=sys.stdout)
            
            # Forward to ANV
            self.anv.receive_account(timestamp + 10.0)
            
        elif valid == 1 and invalid == 1:
            # Invalid login - trigger logout
            print(json.dumps({
                "time": timestamp + 10.0,
                "model": "AAM1",
                "event": "logout",
                "data": {}
            }), file=sys.stdout)

class ANV:
    """Account Number Verifier"""
    
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
        self.process = env.process(self.run())
        
    def receive_account(self, timestamp):
        """Receive account from AAM"""
        # Schedule verification after 10 seconds delay
        self.env.process(self.verify_account(timestamp))
        
    def verify_account(self, timestamp):
        """Verify account with 50% chance of pass/fail"""
        yield self.env.timeout(10.0)
        
        # 50% chance pass, 50% chance fail
        passed = random.random() < 0.5
        
        if passed:
            print(json.dumps({
                "time": timestamp + 10.0,
                "model": "ANV1",
                "event": "verification",
                "data": {
                    "pass": 1,
                    "fail": 0
                }
            }), file=sys.stdout)
            
            # Forward to PV
            self.pv.receive_verification(timestamp + 20.0)
        else:
            print(json.dumps({
                "time": timestamp + 10.0,
                "model": "ANV1",
                "event": "verification",
                "data": {
                    "pass": 0,
                    "fail": 1
                }
            }), file=sys.stdout)
            # End processing - no further events

class PV:
    """Password Verifier"""
    
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm
        self.process = env.process(self.run())
        
    def receive_verification(self, timestamp):
        """Receive verification from ANV"""
        # Schedule password verification after 10 seconds delay
        self.env.process(self.verify_password(timestamp))
        
    def verify_password(self, timestamp):
        """Verify password with 50% chance per attempt"""
        yield self.env.timeout(10.0)
        
        attempts = 0
        success = False
        
        # Keep trying until success (50% chance per attempt)
        while not success:
            attempts += 1
            success = random.random() < 0.5
            
        print(json.dumps({
            "time": timestamp + 10.0,
            "model": "PV1",
            "event": "verification",
            "data": {
                "success": 1,
                "attempts": attempts
            }
        }), file=sys.stdout)
        
        # Forward to BPM
        self.bpm.receive_password_success(timestamp + 20.0, attempts)

class BPM:
    """Bill Payment Manager"""
    
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
        self.process = env.process(self.run())
        
    def receive_password_success(self, timestamp, attempts):
        """Receive successful password verification"""
        # Schedule bill generation after 10 seconds delay
        self.env.process(self.generate_bill(timestamp, attempts))
        
    def generate_bill(self, timestamp, attempts):
        """Generate random bill amount between 0 and 40"""
        yield self.env.timeout(10.0)
        
        # Generate random bill amount between 0 and 40
        amount = random.randint(0, 40)
        
        print(json.dumps({
            "time": timestamp + 10.0,
            "model": "BPM1",
            "event": "bill",
            "data": {
                "amount": amount
            }
        }), file=sys.stdout)
        
        # Forward to TPM
        self.tpm.receive_bill(timestamp + 20.0, amount)

class TPM:
    """Transaction Process Manager"""
    
    def __init__(self, env):
        self.env = env
        self.balance = INITIAL_BALANCE
        self.transaction_count = 0
        self.process = env.process(self.run())
        
    def receive_bill(self, timestamp, amount):
        """Receive bill amount from BPM"""
        # Schedule transaction processing after 10 seconds delay
        self.env.process(self.process_transaction(timestamp, amount))
        
    def process_transaction(self, timestamp, amount):
        """Process transaction and update balance"""
        yield self.env.timeout(10.0)
        
        # Update balance and transaction count
        self.balance -= amount
        self.transaction_count += 1
        
        print(json.dumps({
            "time": timestamp + 10.0,
            "model": "TPM1",
            "event": "transaction",
            "data": {
                "remaining": self.balance,
                "count": self.transaction_count
            }
        }), file=sys.stdout)

def main():
    parser = argparse.ArgumentParser(description='IOBS Discrete Event Simulation')
    parser.add_argument('--simulation_time', type=float, default=SIMULATION_TIME,
                        help='Total simulation time in seconds (default: 1000000.0)')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create components in the correct order to avoid circular reference issues
    tpm = TPM(env)
    bpm = BPM(env, tpm)
    pv = PV(env, bpm)
    anv = ANV(env, pv)
    aam = AAM(env, anv)
    input_reader = InputReader(env, aam)
    
    # Run simulation
    env.run(until=args.simulation_time)

if __name__ == "__main__":
    main()