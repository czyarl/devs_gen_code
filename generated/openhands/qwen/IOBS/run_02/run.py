#!/usr/bin/env python3
"""
Discrete Event Simulation (DES) for Internet Online Banking System (IOBS)
"""
import argparse
import sys
import json
import logging
import time
import random
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
                parts = line.split()
                if len(parts) != 3:
                    logger.warning(f"Invalid input format: {line}")
                    continue
                    
                timestamp = parts[0]
                valid = int(parts[1])
                invalid = int(parts[2])
                
                # Convert timestamp to seconds
                time_parts = timestamp.split(':')
                hours, minutes, seconds, milliseconds = map(int, time_parts)
                timestamp_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
                
                # Emit input event
                print(json.dumps({
                    "time": timestamp_seconds,
                    "model": "input_reader1",
                    "event": "input",
                    "data": {
                        "valid": valid,
                        "invalid": invalid
                    }
                }), file=sys.stdout)
                
                # Forward to AAM and wait for it to complete
                yield from self.aam.receive_input(valid, invalid, timestamp_seconds)
                
            except Exception as e:
                logger.error(f"Error processing input line '{line}': {e}")
                continue
                
        # Keep the process alive
        while True:
            yield self.env.timeout(1000000)

class AAM:
    """Account Access Manager"""
    
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
        self.process = env.process(self.run())
        
    def receive_input(self, valid, invalid, timestamp):
        """Receive input from input_reader1"""
        # Process with 10s delay
        yield self.env.timeout(10)
        
        if valid == 1 and invalid == 0:
            # Valid login - forward to ANV
            print(json.dumps({
                "time": timestamp + 10.0,
                "model": "AAM1",
                "event": "account_generated",
                "data": {}
            }), file=sys.stdout)
            yield from self.anv.receive_account(timestamp + 10.0)
        elif valid == 1 and invalid == 1:
            # Invalid login - trigger logout
            print(json.dumps({
                "time": timestamp + 10.0,
                "model": "AAM1",
                "event": "logout",
                "data": {}
            }), file=sys.stdout)

    def run(self):
        # AAM process - just waits for events
        while True:
            yield self.env.timeout(1000000)  # Wait indefinitely

class ANV:
    """Account Number Verifier"""
    
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
        self.process = env.process(self.run())
        
    def receive_account(self, timestamp):
        """Receive account from AAM"""
        # Process with 10s delay
        yield self.env.timeout(10)
        
        # 50% chance pass, 50% chance fail
        passed = random.choice([True, False])
        
        print(json.dumps({
            "time": timestamp + 10.0,
            "model": "ANV1",
            "event": "verification",
            "data": {
                "pass": 1 if passed else 0,
                "fail": 1 if not passed else 0
            }
        }), file=sys.stdout)
        
        if passed:
            # Forward to PV
            yield from self.pv.receive_verification(timestamp + 10.0)
        # If failed, processing ends here

    def run(self):
        # ANV process - just waits for events
        while True:
            yield self.env.timeout(1000000)  # Wait indefinitely

class PV:
    """Password Verifier"""
    
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm
        self.process = env.process(self.run())
        
    def receive_verification(self, timestamp):
        """Receive verification from ANV"""
        # Process with 10s delay
        yield self.env.timeout(10)
        
        # Keep trying until success (50% chance per attempt)
        attempts = 0
        success = False
        
        while not success:
            attempts += 1
            success = random.choice([True, False])
            
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
        yield from self.bpm.receive_password_success(timestamp + 10.0)

    def run(self):
        # PV process - just waits for events
        while True:
            yield self.env.timeout(1000000)  # Wait indefinitely

class BPM:
    """Bill Payment Manager"""
    
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
        self.process = env.process(self.run())
        
    def receive_password_success(self, timestamp):
        """Receive password success from PV"""
        # Process with 10s delay
        yield self.env.timeout(10)
        
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
        yield from self.tpm.receive_bill(amount, timestamp + 10.0)

    def run(self):
        # BPM process - just waits for events
        while True:
            yield self.env.timeout(1000000)  # Wait indefinitely

class TPM:
    """Transaction Process Manager"""
    
    def __init__(self, env):
        self.env = env
        self.balance = 3000
        self.transaction_count = 0
        self.process = env.process(self.run())
        
    def receive_bill(self, amount, timestamp):
        """Receive bill amount from BPM"""
        # Process with 10s delay
        yield self.env.timeout(10)
        
        # Calculate remaining balance
        if amount <= self.balance:
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
        else:
            logger.warning(f"Transaction failed: bill amount {amount} exceeds balance {self.balance}")

    def run(self):
        # TPM process - just waits for events
        while True:
            yield self.env.timeout(1000000)  # Wait indefinitely

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
    input_reader = InputReader(env, aam)
    
    # Run simulation
    env.run(until=args.simulation_time)
    
    # Ensure all output is flushed
    sys.stdout.flush()
    sys.stderr.flush()

if __name__ == "__main__":
    main()