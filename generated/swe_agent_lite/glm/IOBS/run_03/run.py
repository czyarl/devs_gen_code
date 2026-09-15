#!/usr/bin/env python3
"""
Internet Online Banking System (IOBS) - Discrete Event Simulation
"""

import argparse
import sys
import json
import logging
import random
import time
from collections import deque
import simpy


# Set up logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


# Seed random number generators with system time
random.seed(time.time_ns())


def parse_timestamp(timestamp_str):
    """Parse timestamp from HH:MM:SS:mmm format to seconds"""
    parts = timestamp_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds_parts = parts[2].split('.')
    seconds = int(seconds_parts[0])
    milliseconds = int(seconds_parts[1]) if len(seconds_parts) > 1 else 0
    
    total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
    return total_seconds


def print_event(time, model, event, data):
    """Print event to stdout as JSONL"""
    output = {
        "time": float(time),
        "model": model,
        "event": event,
        "data": data
    }
    print(json.dumps(output))


class InputReader:
    """Reads input from stdin and forwards to AAM"""
    
    def __init__(self, env, aam, simulation_time):
        self.env = env
        self.aam = aam
        self.simulation_time = simulation_time
        self.input_queue = deque()
        self.process = env.process(self.run())
    
    def add_input(self, timestamp, valid, invalid):
        """Add input to the queue"""
        self.input_queue.append((timestamp, valid, invalid))
    
    def run(self):
        """Main process for input reader"""
        # Print start event at t=0
        print_event(0.0, "input_reader1", "start", {})
        
        # Process inputs in order
        while self.input_queue:
            timestamp, valid, invalid = self.input_queue.popleft()
            
            # Wait until the input timestamp
            current_time = self.env.now
            if timestamp > current_time:
                yield self.env.timeout(timestamp - current_time)
            
            # Print input event
            print_event(self.env.now, "input_reader1", "input", {
                "valid": valid,
                "invalid": invalid
            })
            
            # Forward to AAM after 10 second delay
            yield self.env.timeout(10.0)
            
            # Send to AAM
            self.aam.process_request(valid, invalid)


class AAM:
    """Account Access Manager - handles login requests"""
    
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
        self.process = env.process(self.run())
        self.request_queue = deque()
    
    def process_request(self, valid, invalid):
        """Add request to queue"""
        self.request_queue.append((valid, invalid))
    
    def run(self):
        """Main process for AAM"""
        while True:
            if self.request_queue:
                valid, invalid = self.request_queue.popleft()
                
                # Check if valid login
                if valid == 1 and invalid == 0:
                    # Valid login - forward to ANV
                    print_event(self.env.now, "AAM1", "account_generated", {})
                    self.anv.process_account()
                elif valid == 1 and invalid == 1:
                    # Invalid login - trigger logout
                    print_event(self.env.now, "AAM1", "logout", {})
            
            yield self.env.timeout(0.1)  # Small delay to check for new requests


class ANV:
    """Account Number Verifier - verifies account numbers"""
    
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
        self.process = env.process(self.run())
        self.request_queue = deque()
    
    def process_account(self):
        """Add account verification request to queue"""
        self.request_queue.append(1)
    
    def run(self):
        """Main process for ANV"""
        while True:
            if self.request_queue:
                self.request_queue.popleft()
                
                # 50% chance pass, 50% chance fail
                pass_result = 1 if random.random() < 0.5 else 0
                fail_result = 0 if pass_result == 1 else 1
                
                # Print verification event
                print_event(self.env.now, "ANV1", "verification", {
                    "pass": pass_result,
                    "fail": fail_result
                })
                
                # If pass, forward to PV
                if pass_result == 1:
                    self.pv.process_verification()
            
            yield self.env.timeout(0.1)  # Small delay to check for new requests


class PV:
    """Password Verifier - verifies passwords"""
    
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm
        self.process = env.process(self.run())
        self.request_queue = deque()
    
    def process_verification(self):
        """Add password verification request to queue"""
        self.request_queue.append(1)
    
    def run(self):
        """Main process for PV"""
        while True:
            if self.request_queue:
                self.request_queue.popleft()
                
                # Keep trying until success (50% chance per attempt)
                attempts = 0
                while True:
                    attempts += 1
                    if random.random() < 0.5:
                        break
                
                # Print verification event
                print_event(self.env.now, "PV1", "verification", {
                    "success": 1,
                    "attempts": attempts
                })
                
                # Forward to BPM
                self.bpm.process_bill()
            
            yield self.env.timeout(0.1)  # Small delay to check for new requests


class BPM:
    """Bill Payment Manager - generates bill amounts"""
    
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
        self.process = env.process(self.run())
        self.request_queue = deque()
    
    def process_bill(self):
        """Add bill generation request to queue"""
        self.request_queue.append(1)
    
    def run(self):
        """Main process for BPM"""
        while True:
            if self.request_queue:
                self.request_queue.popleft()
                
                # Generate random bill amount between 0 and 40
                # Make sure it doesn't exceed remaining balance
                remaining_balance = self.tpm.get_remaining_balance()
                max_amount = min(40, remaining_balance)
                amount = random.randint(0, max_amount)
                
                # Print bill event
                print_event(self.env.now, "BPM1", "bill", {
                    "amount": amount
                })
                
                # Forward to TPM
                self.tpm.process_transaction(amount)
            
            yield self.env.timeout(0.1)  # Small delay to check for new requests


class TPM:
    """Transaction Process Manager - processes transactions"""
    
    def __init__(self, env):
        self.env = env
        self.process = env.process(self.run())
        self.request_queue = deque()
        self.balance = 3000
        self.transaction_count = 0
    
    def get_remaining_balance(self):
        """Get current remaining balance"""
        return self.balance
    
    def process_transaction(self, amount):
        """Add transaction processing request to queue"""
        self.request_queue.append(amount)
    
    def run(self):
        """Main process for TPM"""
        while True:
            if self.request_queue:
                amount = self.request_queue.popleft()
                
                # Calculate remaining balance
                self.balance -= amount
                self.transaction_count += 1
                
                # Print transaction event
                print_event(self.env.now, "TPM1", "transaction", {
                    "remaining": self.balance,
                    "count": self.transaction_count
                })
            
            yield self.env.timeout(0.1)  # Small delay to check for new requests


def read_stdin_inputs():
    """Read all inputs from stdin"""
    inputs = []
    for line in sys.stdin:
        line = line.strip()
        if line:
            parts = line.split()
            if len(parts) >= 3:
                timestamp_str = parts[0]
                valid = int(parts[1])
                invalid = int(parts[2])
                timestamp = parse_timestamp(timestamp_str)
                inputs.append((timestamp, valid, invalid))
    return inputs


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Internet Online Banking System Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0,
                        help='Total simulation time in seconds')
    args = parser.parse_args()
    
    logger.info(f"Starting IOBS simulation with simulation_time={args.simulation_time}")
    
    # Read inputs from stdin
    inputs = read_stdin_inputs()
    logger.info(f"Read {len(inputs)} input requests")
    
    # Create SimPy environment
    env = simpy.Environment()
    
    # Create entities in order
    tpm = TPM(env)
    bpm = BPM(env, tpm)
    pv = PV(env, bpm)
    anv = ANV(env, pv)
    aam = AAM(env, anv)
    input_reader = InputReader(env, aam, args.simulation_time)
    
    # Add all inputs to the input reader
    for timestamp, valid, invalid in inputs:
        input_reader.add_input(timestamp, valid, invalid)
    
    # Run simulation
    logger.info("Running simulation...")
    env.run(until=args.simulation_time)
    
    logger.info("Simulation completed")


if __name__ == "__main__":
    main()