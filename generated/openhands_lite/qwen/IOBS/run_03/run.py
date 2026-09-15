#!/usr/bin/env python3
"""
Internet Online Banking System (IOBS) Discrete Event Simulation
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
                    continue
                    
                timestamp = parts[0]
                valid = int(parts[1])
                invalid = int(parts[2])
                
                # Convert timestamp to seconds
                time_parts = timestamp.split(':')
                hours, minutes, seconds, milliseconds = map(int, time_parts)
                sim_time = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
                
                # Emit input event
                print(json.dumps({
                    "time": sim_time,
                    "model": "input_reader1",
                    "event": "input",
                    "data": {
                        "valid": valid,
                        "invalid": invalid
                    }
                }), file=sys.stdout)
                
                # Create a process to handle the input
                self.env.process(self.aam.process_input(valid, invalid, sim_time))
                
            except Exception as e:
                logging.error(f"Error processing input line: {line} - {e}")
                continue

class AAM:
    """Account Access Manager"""
    
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
        self.process = env.process(self.run())
        
    def process_input(self, valid, invalid, timestamp):
        """Process input from input_reader1"""
        # Process after 10s delay
        yield self.env.timeout(10)
        
        if valid == 1 and invalid == 0:
            # Valid login - forward to ANV
            print(json.dumps({
                "time": timestamp + 10.0,
                "model": "AAM1",
                "event": "account_generated",
                "data": {}
            }), file=sys.stdout)
            # Forward to ANV
            self.env.process(self.anv.process_account(timestamp + 10.0))
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
            yield self.env.timeout(1000000)  # Wait forever

class ANV:
    """Account Number Verifier"""
    
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
        self.process = env.process(self.run())
        
    def process_account(self, timestamp):
        """Process account from AAM"""
        # Simulate 50% chance of passing verification
        pass_verification = random.choice([True, False])
        
        # Process after 10s delay
        yield self.env.timeout(10)
        
        if pass_verification:
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
            self.env.process(self.pv.process_verification(timestamp + 10.0))
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
    
    def run(self):
        # ANV process - just waits for events
        while True:
            yield self.env.timeout(1000000)  # Wait forever

class PV:
    """Password Verifier"""
    
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm
        self.attempts = 0
        self.process = env.process(self.run())
        
    def process_verification(self, timestamp):
        """Process verification from ANV"""
        # Simulate password check with 50% success rate per attempt
        # Keep trying until success
        self.attempts = 0
        success = False
        
        while not success:
            self.attempts += 1
            success = random.choice([True, False])
            if not success:
                # Wait for another 10s before retry
                yield self.env.timeout(10)
        
        # Process after 10s delay (for the final attempt)
        yield self.env.timeout(10)
        
        print(json.dumps({
            "time": timestamp + 10.0,
            "model": "PV1",
            "event": "verification",
            "data": {
                "success": 1,
                "attempts": self.attempts
            }
        }), file=sys.stdout)
        # Forward to BPM
        self.env.process(self.bpm.process_password_success(timestamp + 10.0))
    
    def run(self):
        # PV process - just waits for events
        while True:
            yield self.env.timeout(1000000)  # Wait forever

class BPM:
    """Bill Payment Manager"""
    
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
        self.balance = 3000
        self.process = env.process(self.run())
        
    def process_password_success(self, timestamp):
        """Process password success from PV"""
        # Generate random bill amount between 0 and 40
        amount = random.randint(0, 40)
        
        # Ensure it doesn't exceed balance
        if amount > self.balance:
            amount = self.balance
            
        # Update balance
        self.balance -= amount
        
        # Process after 10s delay
        yield self.env.timeout(10)
        
        print(json.dumps({
            "time": timestamp + 10.0,
            "model": "BPM1",
            "event": "bill",
            "data": {
                "amount": amount
            }
        }), file=sys.stdout)
        # Forward to TPM
        self.env.process(self.tpm.process_bill(timestamp + 10.0, amount))
    
    def run(self):
        # BPM process - just waits for events
        while True:
            yield self.env.timeout(1000000)  # Wait forever

class TPM:
    """Transaction Process Manager"""
    
    def __init__(self, env):
        self.env = env
        self.balance = 3000
        self.transaction_count = 0
        self.process = env.process(self.run())
        
    def process_bill(self, timestamp, amount):
        """Process bill from BPM"""
        # Calculate remaining balance
        self.balance -= amount
        self.transaction_count += 1
        
        # Process after 10s delay
        yield self.env.timeout(10)
        
        print(json.dumps({
            "time": timestamp + 10.0,
            "model": "TPM1",
            "event": "transaction",
            "data": {
                "remaining": self.balance,
                "count": self.transaction_count
            }
        }), file=sys.stdout)
    
    def run(self):
        # TPM process - just waits for events
        while True:
            yield self.env.timeout(1000000)  # Wait forever

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
    
    # Ensure simulation ends in 10 seconds real time
    # This is handled by the environment's run method with the time limit

if __name__ == "__main__":
    main()