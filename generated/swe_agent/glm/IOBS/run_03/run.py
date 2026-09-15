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
import simpy
from collections import deque

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Set random seed using system time
random.seed(time.time_ns())

# Constants
PROCESSING_DELAY = 10.0  # 10 seconds per entity
INITIAL_BALANCE = 3000


def parse_timestamp(timestamp_str):
    """Parse timestamp from HH:MM:SS:mmm format to seconds"""
    parts = timestamp_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = 0
    if len(parts) >= 4:
        milliseconds = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def output_event(time, model, event, data):
    """Output event to stdout as JSONL"""
    event_obj = {
        "time": time,
        "model": model,
        "event": event,
        "data": data
    }
    print(json.dumps(event_obj))


class InputReader:
    """Reads input from stdin and forwards to AAM"""
    
    def __init__(self, env, aam, simulation_time):
        self.env = env
        self.aam = aam
        self.simulation_time = simulation_time
        self.requests = deque()
        
    def read_input(self):
        """Read all input from stdin"""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 3:
                timestamp_str = parts[0]
                valid = int(parts[1])
                invalid = int(parts[2])
                timestamp = parse_timestamp(timestamp_str)
                self.requests.append((timestamp, valid, invalid))
        
        # Sort requests by timestamp
        self.requests = deque(sorted(self.requests, key=lambda x: x[0]))
    
    def run(self):
        """Main process for input reader"""
        # Output start event at t=0
        output_event(0.0, "input_reader1", "start", {})
        
        # Read all input
        self.read_input()
        
        # Process each request
        while self.requests:
            timestamp, valid, invalid = self.requests.popleft()
            
            # Wait until the request timestamp
            if self.env.now < timestamp:
                yield self.env.timeout(timestamp - self.env.now)
            
            # Output input event
            output_event(self.env.now, "input_reader1", "input", {"valid": valid, "invalid": invalid})
            
            # Forward to AAM (start processing)
            self.env.process(self.aam.process_request(valid, invalid))


class AAM:
    """Account Access Manager"""
    
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
    
    def process_request(self, valid, invalid):
        """Receive request from input reader"""
        # Wait for processing delay
        yield self.env.timeout(PROCESSING_DELAY)
        
        if valid == 1 and invalid == 0:
            # Valid login - forward to ANV
            output_event(self.env.now, "AAM1", "account_generated", {})
            self.env.process(self.anv.process_account())
        elif valid == 1 and invalid == 1:
            # Invalid login - trigger logout
            output_event(self.env.now, "AAM1", "logout", {})


class ANV:
    """Account Number Verifier"""
    
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
    
    def process_account(self):
        """Receive account from AAM"""
        # Wait for processing delay
        yield self.env.timeout(PROCESSING_DELAY)
        
        # 50% chance pass, 50% chance fail
        if random.random() < 0.5:
            # Pass - forward to PV
            output_event(self.env.now, "ANV1", "verification", {"pass": 1, "fail": 0})
            self.env.process(self.pv.process_verification())
        else:
            # Fail - end processing
            output_event(self.env.now, "ANV1", "verification", {"pass": 0, "fail": 1})


class PV:
    """Password Verifier"""
    
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm
    
    def process_verification(self):
        """Receive verification from ANV"""
        attempts = 0
        success = False
        
        # Keep trying until success (50% chance per attempt)
        while not success:
            attempts += 1
            # Wait for processing delay for each attempt
            yield self.env.timeout(PROCESSING_DELAY)
            
            if random.random() < 0.5:
                success = True
        
        # Success - forward to BPM
        output_event(self.env.now, "PV1", "verification", {"success": 1, "attempts": attempts})
        self.env.process(self.bpm.process_bill())


class BPM:
    """Bill Payment Manager"""
    
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
    
    def process_bill(self):
        """Receive verification from PV"""
        # Wait for processing delay
        yield self.env.timeout(PROCESSING_DELAY)
        
        # Generate random bill amount between 0 and 40
        # Make sure it doesn't exceed remaining balance
        remaining_balance = self.tpm.get_remaining_balance()
        max_amount = min(40, remaining_balance)
        amount = random.randint(0, max_amount)
        
        # Output bill event
        output_event(self.env.now, "BPM1", "bill", {"amount": amount})
        
        # Forward to TPM
        self.env.process(self.tpm.process_transaction(amount))


class TPM:
    """Transaction Process Manager"""
    
    def __init__(self, env):
        self.env = env
        self.balance = INITIAL_BALANCE
        self.transaction_count = 0
    
    def get_remaining_balance(self):
        """Get current remaining balance"""
        return self.balance
    
    def process_transaction(self, amount):
        """Receive bill amount from BPM"""
        # Wait for processing delay
        yield self.env.timeout(PROCESSING_DELAY)
        
        # Calculate remaining balance
        self.balance -= amount
        self.transaction_count += 1
        
        # Output transaction event
        output_event(self.env.now, "TPM1", "transaction", {
            "remaining": self.balance,
            "count": self.transaction_count
        })


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Internet Online Banking System Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0,
                        help='Total simulation time in seconds')
    args = parser.parse_args()
    
    logger.info(f"Starting IOBS simulation with simulation_time={args.simulation_time}")
    
    # Create SimPy environment
    env = simpy.Environment()
    
    # Create entities
    tpm = TPM(env)
    bpm = BPM(env, tpm)
    pv = PV(env, bpm)
    anv = ANV(env, pv)
    aam = AAM(env, anv)
    input_reader = InputReader(env, aam, args.simulation_time)
    
    # Start processes
    env.process(input_reader.run())
    
    # Run simulation
    logger.info("Running simulation...")
    env.run(until=args.simulation_time)
    
    logger.info("Simulation completed")


if __name__ == "__main__":
    main()
