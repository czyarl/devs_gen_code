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
        self.process = env.process(self.run())
    
    def run(self):
        """Main process for input reader"""
        output_event(self.env.now, "input_reader1", "start", {})
        
        # Read all input lines first
        requests = []
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
                requests.append((timestamp, valid, invalid))
        
        # Sort requests by timestamp
        requests.sort(key=lambda x: x[0])
        
        # Process each request
        for timestamp, valid, invalid in requests:
            if self.env.now >= self.simulation_time:
                break
            
            # Wait until the request timestamp
            if timestamp > self.env.now:
                yield self.env.timeout(timestamp - self.env.now)
            
            if self.env.now >= self.simulation_time:
                break
            
            # Output input event
            output_event(self.env.now, "input_reader1", "input", {"valid": valid, "invalid": invalid})
            
            # Forward to AAM with 10s delay
            yield self.env.timeout(10)
            
            if self.env.now >= self.simulation_time:
                break
            
            # Send to AAM
            self.aam.process_request(valid, invalid)


class AAM:
    """Account Access Manager - validates login requests"""
    
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
    
    def process_request(self, valid, invalid):
        """Process login request"""
        if valid == 1 and invalid == 0:
            # Valid login - forward to ANV
            output_event(self.env.now, "AAM1", "account_generated", {})
            self.env.process(self.anv.verify_account())
        elif valid == 1 and invalid == 1:
            # Invalid login - trigger logout
            output_event(self.env.now, "AAM1", "logout", {})


class ANV:
    """Account Number Verifier - 50% pass/fail"""
    
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
    
    def verify_account(self):
        """Verify account number with 50% pass rate"""
        # 10s delay for processing
        yield self.env.timeout(10)
        
        # Random verification: 50% pass, 50% fail
        if random.random() < 0.5:
            pass_result = 1
            fail_result = 0
            # Forward to PV
            self.env.process(self.pv.verify_password())
        else:
            pass_result = 0
            fail_result = 1
        
        output_event(self.env.now, "ANV1", "verification", {"pass": pass_result, "fail": fail_result})


class PV:
    """Password Verifier - 50% success per attempt, retries until success"""
    
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm
    
    def verify_password(self):
        """Verify password with 50% success rate per attempt"""
        attempts = 0
        
        while True:
            attempts += 1
            # 10s delay for each attempt
            yield self.env.timeout(10)
            
            # 50% chance of success
            if random.random() < 0.5:
                # Success - forward to BPM
                output_event(self.env.now, "PV1", "verification", {"success": 1, "attempts": attempts})
                self.env.process(self.bpm.generate_bill())
                break


class BPM:
    """Bill Payment Manager - generates random bill amount"""
    
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
    
    def generate_bill(self):
        """Generate random bill amount (0-40)"""
        # 10s delay for processing
        yield self.env.timeout(10)
        
        # Generate random amount between 0 and 40
        amount = random.randint(0, 40)
        
        output_event(self.env.now, "BPM1", "bill", {"amount": amount})
        
        # Forward to TPM
        self.env.process(self.tpm.process_transaction(amount))


class TPM:
    """Transaction Process Manager - tracks balance and count"""
    
    def __init__(self, env):
        self.env = env
        self.balance = 3000
        self.count = 0
    
    def process_transaction(self, amount):
        """Process transaction and update balance"""
        # 10s delay for processing
        yield self.env.timeout(10)
        
        # Calculate remaining balance
        remaining = self.balance - amount
        self.balance = remaining
        self.count += 1
        
        output_event(self.env.now, "TPM1", "transaction", {"remaining": remaining, "count": self.count})


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Internet Online Banking System Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0,
                        help='Total simulation time in seconds')
    args = parser.parse_args()
    
    logger.info(f"Starting IOBS simulation with simulation_time={args.simulation_time}")
    
    # Create simpy environment
    env = simpy.Environment()
    
    # Create components
    tpm = TPM(env)
    bpm = BPM(env, tpm)
    pv = PV(env, bpm)
    anv = ANV(env, pv)
    aam = AAM(env, anv)
    input_reader = InputReader(env, aam, args.simulation_time)
    
    # Run simulation
    env.run(until=args.simulation_time)
    
    logger.info("Simulation completed")


if __name__ == "__main__":
    main()
