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
logging.basicConfig(stream=sys.stderr, level=logging.INFO)
logger = logging.getLogger(__name__)

# Set random seed using system time
random.seed(time.time_ns())


def parse_timestamp(timestamp_str):
    """Parse timestamp from HH:MM:SS:mmm format to seconds."""
    parts = timestamp_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds_parts = parts[2].split('.')
    seconds = int(seconds_parts[0])
    milliseconds = int(seconds_parts[1]) if len(seconds_parts) > 1 else 0
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def output_event(time, model, event, data):
    """Output an event to stdout as JSONL."""
    event_obj = {
        "time": time,
        "model": model,
        "event": event,
        "data": data
    }
    print(json.dumps(event_obj))


class InputReader:
    """Reads input from stdin and forwards to AAM."""
    
    def __init__(self, env, aam):
        self.env = env
        self.aam = aam
        self.process = env.process(self.run())
    
    def run(self):
        """Main process for input reader."""
        output_event(self.env.now, "input_reader1", "start", {})
        
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split()
            timestamp_str = parts[0]
            valid = int(parts[1])
            invalid = int(parts[2])
            
            # Wait until the timestamp
            target_time = parse_timestamp(timestamp_str)
            if self.env.now < target_time:
                yield self.env.timeout(target_time - self.env.now)
            
            # Output input event
            output_event(self.env.now, "input_reader1", "input", {
                "valid": valid,
                "invalid": invalid
            })
            
            # Forward to AAM
            self.aam.receive_request(valid, invalid)
        
        # Signal that input is complete
        self.aam.input_complete()


class AAM:
    """Account Access Manager - Handles login requests."""
    
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
        self.process = env.process(self.run())
        self.request_queue = []
        self.input_done = False
    
    def receive_request(self, valid, invalid):
        """Receive a login request."""
        self.request_queue.append((valid, invalid))
    
    def input_complete(self):
        """Signal that input is complete."""
        self.input_done = True
    
    def run(self):
        """Main process for AAM."""
        while True:
            if self.request_queue:
                valid, invalid = self.request_queue.pop(0)
                
                # Processing delay of 10 seconds
                yield self.env.timeout(10)
                
                if valid == 1 and invalid == 0:
                    # Valid login - forward to ANV
                    output_event(self.env.now, "AAM1", "account_generated", {})
                    self.anv.receive_account()
                elif valid == 1 and invalid == 1:
                    # Invalid login - trigger logout
                    output_event(self.env.now, "AAM1", "logout", {})
            elif self.input_done:
                # Input is complete and queue is empty - signal ANV and exit
                self.anv.input_complete()
                break
            else:
                yield self.env.timeout(0.1)


class ANV:
    """Account Number Verifier - Verifies account numbers."""
    
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
        self.process = env.process(self.run())
        self.account_queue = []
        self.input_done = False
    
    def receive_account(self):
        """Receive an account to verify."""
        self.account_queue.append(1)
    
    def input_complete(self):
        """Signal that input is complete."""
        self.input_done = True
    
    def run(self):
        """Main process for ANV."""
        while True:
            if self.account_queue:
                self.account_queue.pop(0)
                
                # Processing delay of 10 seconds
                yield self.env.timeout(10)
                
                # Random verification: 50% pass, 50% fail
                if random.random() < 0.5:
                    # Pass - forward to PV
                    output_event(self.env.now, "ANV1", "verification", {
                        "pass": 1,
                        "fail": 0
                    })
                    self.pv.receive_verification()
                else:
                    # Fail - end processing
                    output_event(self.env.now, "ANV1", "verification", {
                        "pass": 0,
                        "fail": 1
                    })
            elif self.input_done:
                # Input is complete and queue is empty - signal PV and exit
                self.pv.input_complete()
                break
            else:
                yield self.env.timeout(0.1)


class PV:
    """Password Verifier - Verifies passwords."""
    
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm
        self.process = env.process(self.run())
        self.verification_queue = []
        self.input_done = False
    
    def receive_verification(self):
        """Receive a verification request."""
        self.verification_queue.append(1)
    
    def input_complete(self):
        """Signal that input is complete."""
        self.input_done = True
    
    def run(self):
        """Main process for PV."""
        while True:
            if self.verification_queue:
                self.verification_queue.pop(0)
                
                # Keep trying until success (50% chance per attempt)
                attempts = 0
                while True:
                    attempts += 1
                    # Processing delay of 10 seconds per attempt
                    yield self.env.timeout(10)
                    
                    if random.random() < 0.5:
                        # Success - forward to BPM
                        output_event(self.env.now, "PV1", "verification", {
                            "success": 1,
                            "attempts": attempts
                        })
                        self.bpm.receive_verification()
                        break
            elif self.input_done:
                # Input is complete and queue is empty - signal BPM and exit
                self.bpm.input_complete()
                break
            else:
                yield self.env.timeout(0.1)


class BPM:
    """Bill Payment Manager - Generates bill amounts."""
    
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
        self.process = env.process(self.run())
        self.verification_queue = []
        self.input_done = False
    
    def receive_verification(self):
        """Receive a verification request."""
        self.verification_queue.append(1)
    
    def input_complete(self):
        """Signal that input is complete."""
        self.input_done = True
    
    def run(self):
        """Main process for BPM."""
        while True:
            if self.verification_queue:
                self.verification_queue.pop(0)
                
                # Processing delay of 10 seconds
                yield self.env.timeout(10)
                
                # Generate random bill amount between 0 and 40
                # Get remaining balance from TPM
                remaining_balance = self.tpm.get_remaining_balance()
                
                # Make sure amount doesn't exceed remaining balance
                max_amount = min(40, remaining_balance)
                amount = random.randint(0, max_amount)
                
                output_event(self.env.now, "BPM1", "bill", {
                    "amount": amount
                })
                
                # Forward to TPM
                self.tpm.receive_bill(amount)
            elif self.input_done:
                # Input is complete and queue is empty - signal TPM and exit
                self.tpm.input_complete()
                break
            else:
                yield self.env.timeout(0.1)


class TPM:
    """Transaction Process Manager - Processes transactions."""
    
    def __init__(self, env):
        self.env = env
        self.process = env.process(self.run())
        self.bill_queue = []
        self.balance = 3000
        self.transaction_count = 0
        self.input_done = False
    
    def get_remaining_balance(self):
        """Get the current remaining balance."""
        return self.balance
    
    def receive_bill(self, amount):
        """Receive a bill to process."""
        self.bill_queue.append(amount)
    
    def input_complete(self):
        """Signal that input is complete."""
        self.input_done = True
    
    def run(self):
        """Main process for TPM."""
        while True:
            if self.bill_queue:
                amount = self.bill_queue.pop(0)
                
                # Processing delay of 10 seconds
                yield self.env.timeout(10)
                
                # Calculate remaining balance
                self.balance -= amount
                self.transaction_count += 1
                
                output_event(self.env.now, "TPM1", "transaction", {
                    "remaining": self.balance,
                    "count": self.transaction_count
                })
            elif self.input_done:
                # Input is complete and queue is empty - exit
                break
            else:
                yield self.env.timeout(0.1)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Internet Online Banking System Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0,
                        help='Total simulation time in seconds')
    args = parser.parse_args()
    
    # Create simpy environment
    env = simpy.Environment()
    
    # Create TPM first (needed by BPM)
    tpm = TPM(env)
    
    # Create other entities
    bpm = BPM(env, tpm)
    pv = PV(env, bpm)
    anv = ANV(env, pv)
    aam = AAM(env, anv)
    input_reader = InputReader(env, aam)
    
    # Run simulation
    logger.info(f"Starting simulation for {args.simulation_time} seconds")
    env.run(until=args.simulation_time)
    logger.info("Simulation completed")


if __name__ == '__main__':
    main()