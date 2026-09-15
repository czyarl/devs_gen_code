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

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Set random seed using system time
random.seed(time.time_ns())

# Constants
PROCESSING_DELAY = 10.0  # seconds
INITIAL_BALANCE = 3000


def parse_timestamp(timestamp_str):
    """Parse HH:MM:SS:mmm format to seconds"""
    parts = timestamp_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3]) if len(parts) > 3 else 0
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def output_event(time, model, event, data):
    """Output event in JSONL format to stdout"""
    event_obj = {
        "time": time,
        "model": model,
        "event": event,
        "data": data
    }
    print(json.dumps(event_obj))


class InputReader:
    """Reads input from stdin and forwards to AAM"""
    
    def __init__(self, env, aam):
        self.env = env
        self.aam = aam
        self.requests = []
    
    def read_input(self):
        """Read all input lines and parse them"""
        output_event(0.0, "input_reader1", "start", {})
        
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
        self.requests.sort(key=lambda x: x[0])
        
        # Process each request
        for timestamp, valid, invalid in self.requests:
            # Wait until the request timestamp
            yield self.env.timeout(timestamp - self.env.now)
            
            # Output input event
            output_event(self.env.now, "input_reader1", "input", {
                "valid": valid,
                "invalid": invalid
            })
            
            # Forward to AAM
            self.env.process(self.aam.process(valid, invalid))


class AAM:
    """Account Access Manager - validates login requests"""
    
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
    
    def process(self, valid, invalid):
        """Process login request"""
        # Processing delay
        yield self.env.timeout(PROCESSING_DELAY)
        
        if valid == 1 and invalid == 0:
            # Valid login - forward to ANV
            output_event(self.env.now, "AAM1", "account_generated", {})
            self.env.process(self.anv.process())
        elif valid == 1 and invalid == 1:
            # Invalid login - logout
            output_event(self.env.now, "AAM1", "logout", {})


class ANV:
    """Account Number Verifier - 50% pass/fail"""
    
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
    
    def process(self):
        """Process account verification"""
        # Processing delay
        yield self.env.timeout(PROCESSING_DELAY)
        
        # 50% chance pass, 50% chance fail
        pass_result = 1 if random.random() < 0.5 else 0
        fail_result = 0 if pass_result == 1 else 1
        
        output_event(self.env.now, "ANV1", "verification", {
            "pass": pass_result,
            "fail": fail_result
        })
        
        if pass_result == 1:
            # Forward to PV
            self.env.process(self.pv.process())


class PV:
    """Password Verifier - retries until success"""
    
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm
    
    def process(self):
        """Process password verification"""
        attempts = 0
        success = False
        
        while not success:
            attempts += 1
            # 50% chance success per attempt
            success = random.random() < 0.5
            
            if not success:
                # Retry delay (part of processing time)
                yield self.env.timeout(PROCESSING_DELAY)
        
        # Final processing delay for successful attempt
        yield self.env.timeout(PROCESSING_DELAY)
        
        output_event(self.env.now, "PV1", "verification", {
            "success": 1,
            "attempts": attempts
        })
        
        # Forward to BPM
        self.env.process(self.bpm.process())


class BPM:
    """Bill Payment Manager - generates bill amount"""
    
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
    
    def process(self):
        """Process bill generation"""
        # Processing delay
        yield self.env.timeout(PROCESSING_DELAY)
        
        # Generate random bill amount between 0 and 40
        # Will be constrained by remaining balance in TPM
        amount = random.randint(0, 40)
        
        output_event(self.env.now, "BPM1", "bill", {
            "amount": amount
        })
        
        # Forward to TPM
        self.env.process(self.tpm.process(amount))


class TPM:
    """Transaction Process Manager - processes transactions"""
    
    def __init__(self, env):
        self.env = env
        self.balance = INITIAL_BALANCE
        self.count = 0
    
    def process(self, amount):
        """Process transaction"""
        # Processing delay
        yield self.env.timeout(PROCESSING_DELAY)
        
        # Ensure amount doesn't exceed remaining balance
        if amount > self.balance:
            amount = self.balance
        
        # Calculate remaining balance
        self.balance -= amount
        self.count += 1
        
        output_event(self.env.now, "TPM1", "transaction", {
            "remaining": self.balance,
            "count": self.count
        })


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Internet Online Banking System Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0,
                        help='Total simulation time in seconds')
    args = parser.parse_args()
    
    logger.info(f"Starting IOBS simulation with max time: {args.simulation_time}s")
    
    # Create simpy environment
    env = simpy.Environment()
    
    # Create entities
    tpm = TPM(env)
    bpm = BPM(env, tpm)
    pv = PV(env, bpm)
    anv = ANV(env, pv)
    aam = AAM(env, anv)
    input_reader = InputReader(env, aam)
    
    # Start input reader
    env.process(input_reader.read_input())
    
    # Run simulation
    env.run(until=args.simulation_time)
    
    logger.info("Simulation completed")


if __name__ == "__main__":
    main()