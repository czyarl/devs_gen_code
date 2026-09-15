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

# Set random seed using system time
random.seed(time.time_ns())

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


def parse_timestamp(timestamp_str):
    """Parse timestamp from HH:MM:SS:mmm format to seconds"""
    parts = timestamp_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3]) if len(parts) > 3 else 0
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def output_event(time, model, event, data):
    """Output event as JSONL to stdout"""
    event_obj = {
        "time": time,
        "model": model,
        "event": event,
        "data": data
    }
    print(json.dumps(event_obj))
    sys.stdout.flush()


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
                try:
                    timestamp_str = parts[0]
                    valid = int(parts[1])
                    invalid = int(parts[2])
                    timestamp = parse_timestamp(timestamp_str)
                    self.requests.append((timestamp, valid, invalid))
                except (ValueError, IndexError):
                    # Skip invalid lines
                    logger.warning(f"Skipping invalid line: {line}")
                    continue
        
        # Sort requests by timestamp
        self.requests = deque(sorted(self.requests, key=lambda x: x[0]))
        logger.info(f"Read {len(self.requests)} requests from stdin")
    
    def process(self):
        """Process input requests"""
        output_event(self.env.now, "input_reader1", "start", {})
        
        while self.requests:
            timestamp, valid, invalid = self.requests.popleft()
            
            # Wait until the request timestamp
            if self.env.now < timestamp:
                yield self.env.timeout(timestamp - self.env.now)
            
            # Output input event at the request timestamp
            output_event(self.env.now, "input_reader1", "input", {
                "valid": valid,
                "invalid": invalid
            })
            
            # Forward to AAM
            self.aam.process_request(valid, invalid)


class AAM:
    """Account Access Manager - handles login requests"""
    
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
        self.pending_requests = deque()
    
    def process_request(self, valid, invalid):
        """Queue a request for processing"""
        self.pending_requests.append((valid, invalid))
    
    def process(self):
        """Process queued requests"""
        while True:
            if self.pending_requests:
                valid, invalid = self.pending_requests.popleft()
                
                # Processing delay
                yield self.env.timeout(10)
                
                if valid == 1 and invalid == 0:
                    # Valid login - forward to ANV
                    output_event(self.env.now, "AAM1", "account_generated", {})
                    self.anv.process_request()
                elif valid == 1 and invalid == 1:
                    # Invalid login - trigger logout
                    output_event(self.env.now, "AAM1", "logout", {})
            else:
                yield self.env.timeout(1)


class ANV:
    """Account Number Verifier - verifies account numbers"""
    
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
        self.pending_requests = deque()
    
    def process_request(self):
        """Queue a request for processing"""
        self.pending_requests.append(1)
    
    def process(self):
        """Process queued requests"""
        while True:
            if self.pending_requests:
                self.pending_requests.popleft()
                
                # Processing delay
                yield self.env.timeout(10)
                
                # Random verification: 50% pass, 50% fail
                pass_result = 1 if random.random() < 0.5 else 0
                fail_result = 1 - pass_result
                
                output_event(self.env.now, "ANV1", "verification", {
                    "pass": pass_result,
                    "fail": fail_result
                })
                
                if pass_result == 1:
                    # Forward to PV
                    self.pv.process_request()
            else:
                yield self.env.timeout(1)


class PV:
    """Password Verifier - verifies passwords"""
    
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm
        self.pending_requests = deque()
    
    def process_request(self):
        """Queue a request for processing"""
        self.pending_requests.append(1)
    
    def process(self):
        """Process queued requests"""
        while True:
            if self.pending_requests:
                self.pending_requests.popleft()
                
                # Processing delay (10 seconds total)
                yield self.env.timeout(10)
                
                # Keep trying until success (50% chance per attempt)
                attempts = 0
                while True:
                    attempts += 1
                    if random.random() < 0.5:
                        # Success
                        break
                
                output_event(self.env.now, "PV1", "verification", {
                    "success": 1,
                    "attempts": attempts
                })
                
                # Forward to BPM
                self.bpm.process_request()
            else:
                yield self.env.timeout(1)


class BPM:
    """Bill Payment Manager - generates bill amounts"""
    
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
        self.pending_requests = deque()
    
    def process_request(self):
        """Queue a request for processing"""
        self.pending_requests.append(1)
    
    def process(self):
        """Process queued requests"""
        while True:
            if self.pending_requests:
                self.pending_requests.popleft()
                
                # Processing delay
                yield self.env.timeout(10)
                
                # Generate random bill amount between 0 and 40
                # Make sure it doesn't exceed remaining balance
                remaining_balance = self.tpm.get_remaining_balance()
                max_amount = min(40, remaining_balance)
                amount = random.randint(0, max_amount)
                
                output_event(self.env.now, "BPM1", "bill", {
                    "amount": amount
                })
                
                # Forward to TPM
                self.tpm.process_request(amount)
            else:
                yield self.env.timeout(1)


class TPM:
    """Transaction Process Manager - processes transactions"""
    
    def __init__(self, env):
        self.env = env
        self.balance = 3000
        self.transaction_count = 0
        self.pending_requests = deque()
    
    def get_remaining_balance(self):
        """Get current remaining balance"""
        return self.balance
    
    def process_request(self, amount):
        """Queue a request for processing"""
        self.pending_requests.append(amount)
    
    def process(self):
        """Process queued requests"""
        while True:
            if self.pending_requests:
                amount = self.pending_requests.popleft()
                
                # Processing delay
                yield self.env.timeout(10)
                
                # Calculate remaining balance
                self.balance -= amount
                self.transaction_count += 1
                
                output_event(self.env.now, "TPM1", "transaction", {
                    "remaining": self.balance,
                    "count": self.transaction_count
                })
            else:
                yield self.env.timeout(1)


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
    
    # Read input
    input_reader.read_input()
    
    # Start entity processes
    env.process(input_reader.process())
    env.process(aam.process())
    env.process(anv.process())
    env.process(pv.process())
    env.process(bpm.process())
    env.process(tpm.process())
    
    # Run simulation
    env.run(until=args.simulation_time)
    
    logger.info("Simulation completed")


if __name__ == "__main__":
    main()