#!/usr/bin/env python3
"""
Discrete Event Simulation (DES) for Internet Online Banking System (IOBS)
"""
import argparse
import sys
import json
import time
import random
import simpy


class InputReader:
    """Reads input from stdin and forwards to AAM"""
    
    def __init__(self, env, aam):
        self.env = env
        self.aam = aam
        # No need for process here - it's handled in the run method
        self.env.process(self.run())
        
    def run(self):
        # Emit start event at t=0
        yield self.env.timeout(0)
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
                # Parse timestamp and flags
                timestamp_str, valid_str, invalid_str = line.split()
                valid = int(valid_str)
                invalid = int(invalid_str)
                
                # Convert timestamp to seconds
                h, m, s, ms = map(int, timestamp_str.split(':'))
                timestamp = h * 3600 + m * 60 + s + ms / 1000.0
                
                # Emit input event
                yield self.env.timeout(timestamp)
                print(json.dumps({
                    "time": timestamp,
                    "model": "input_reader1",
                    "event": "input",
                    "data": {
                        "valid": valid,
                        "invalid": invalid
                    }
                }), file=sys.stdout)
                
                # Forward to AAM
                self.aam.receive_input(valid, invalid, timestamp)
                
            except Exception as e:
                print(f"Error processing input line '{line}': {e}", file=sys.stderr)
                continue


class AAM:
    """Account Access Manager"""
    
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
        # No process needed - it's handled in the receive_input method
        
    def receive_input(self, valid, invalid, timestamp):
        """Receive input from input_reader1"""
        # Store the request for processing
        self.current_request = {
            'valid': valid,
            'invalid': invalid,
            'timestamp': timestamp
        }
        
        # Process the request
        self.env.process(self.process_request())
        
    def process_request(self):
        """Process the request with 10s delay"""
        yield self.env.timeout(10.0)
        
        # Check if request is valid
        if self.current_request['valid'] == 1 and self.current_request['invalid'] == 0:
            # Valid login - forward to ANV
            print(json.dumps({
                "time": self.current_request['timestamp'] + 10.0,
                "model": "AAM1",
                "event": "account_generated",
                "data": {}
            }), file=sys.stdout)
            
            # Forward to ANV
            self.anv.receive_account(self.current_request['timestamp'] + 10.0)
        else:
            # Invalid login - trigger logout
            print(json.dumps({
                "time": self.current_request['timestamp'] + 10.0,
                "model": "AAM1",
                "event": "logout",
                "data": {}
            }), file=sys.stdout)


class ANV:
    """Account Number Verifier"""
    
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
        # No process needed - it's handled in the receive_account method
        
    def receive_account(self, timestamp):
        """Receive account from AAM"""
        self.current_timestamp = timestamp
        self.env.process(self.verify_account())
        
    def verify_account(self):
        """Verify account with 50% chance of passing/failing"""
        yield self.env.timeout(10.0)
        
        # 50% chance of passing
        passed = random.random() < 0.5
        
        print(json.dumps({
            "time": self.current_timestamp + 10.0,
            "model": "ANV1",
            "event": "verification",
            "data": {
                "pass": 1 if passed else 0,
                "fail": 0 if passed else 1
            }
        }), file=sys.stdout)
        
        if passed:
            # Forward to PV
            self.pv.receive_verification(self.current_timestamp + 20.0)
        # If failed, processing ends here


class PV:
    """Password Verifier"""
    
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm
        self.attempts = 0
        # No process needed - it's handled in the receive_verification method
        
    def receive_verification(self, timestamp):
        """Receive verification from ANV"""
        self.current_timestamp = timestamp
        self.env.process(self.verify_password())
        
    def verify_password(self):
        """Verify password with 50% chance of success per attempt"""
        yield self.env.timeout(10.0)
        
        # Keep trying until success (50% chance per attempt)
        success = False
        self.attempts = 0
        
        while not success:
            self.attempts += 1
            success = random.random() < 0.5
            
        print(json.dumps({
            "time": self.current_timestamp + 10.0,
            "model": "PV1",
            "event": "verification",
            "data": {
                "success": 1,
                "attempts": self.attempts
            }
        }), file=sys.stdout)
        
        # Forward to BPM
        self.bpm.receive_bill_request(self.current_timestamp + 20.0)


class BPM:
    """Bill Payment Manager"""
    
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
        # No process needed - it's handled in the receive_bill_request method
        
    def receive_bill_request(self, timestamp):
        """Receive bill request from PV"""
        self.current_timestamp = timestamp
        self.env.process(self.generate_bill())
        
    def generate_bill(self):
        """Generate random bill amount between 0 and 40"""
        yield self.env.timeout(10.0)
        
        # Generate random bill amount (0-40)
        amount = random.randint(0, 40)
        
        print(json.dumps({
            "time": self.current_timestamp + 10.0,
            "model": "BPM1",
            "event": "bill",
            "data": {
                "amount": amount
            }
        }), file=sys.stdout)
        
        # Forward to TPM
        self.tpm.receive_transaction(amount, self.current_timestamp + 20.0)


class TPM:
    """Transaction Process Manager"""
    
    def __init__(self, env):
        self.env = env
        self.balance = 3000
        self.transaction_count = 0
        
    def receive_transaction(self, amount, timestamp):
        """Receive transaction from BPM"""
        self.current_amount = amount
        self.current_timestamp = timestamp
        self.env.process(self.process_transaction())
        
    def process_transaction(self):
        """Process transaction with balance tracking"""
        yield self.env.timeout(10.0)
        
        # Calculate remaining balance
        self.balance -= self.current_amount
        self.transaction_count += 1
        
        print(json.dumps({
            "time": self.current_timestamp + 10.0,
            "model": "TPM1",
            "event": "transaction",
            "data": {
                "remaining": self.balance,
                "count": self.transaction_count
            }
        }), file=sys.stdout)


def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulation_time', type=float, default=1000000.0,
                        help='Total simulation time in seconds')
    args = parser.parse_args()
    
    # Set random seed using system time
    random.seed(time.time_ns())
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create entities in the correct order to avoid circular references
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