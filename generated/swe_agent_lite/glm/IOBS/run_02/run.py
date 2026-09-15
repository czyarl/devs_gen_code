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


# Setup logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


# Seed random number generators with system time
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
    """Output an event in JSONL format to stdout."""
    event_obj = {
        "time": float(time),
        "model": model,
        "event": event,
        "data": data
    }
    print(json.dumps(event_obj))
    sys.stdout.flush()


class InputReader:
    """Reads input from stdin and forwards to AAM."""
    
    def __init__(self, env, aam):
        self.env = env
        self.aam = aam
        self.requests = deque()
        
    def load_requests(self):
        """Load all requests from stdin."""
        for line in sys.stdin:
            line = line.strip()
            if line:
                parts = line.split()
                if len(parts) >= 3:
                    timestamp_str = parts[0]
                    valid = int(parts[1])
                    invalid = int(parts[2])
                    timestamp = parse_timestamp(timestamp_str)
                    self.requests.append((timestamp, valid, invalid))
    
    def process(self):
        """Process input requests."""
        # Output start event at t=0
        output_event(0.0, "input_reader1", "start", {})
        
        while self.requests:
            timestamp, valid, invalid = self.requests.popleft()
            
            # Wait until the request timestamp
            wait_time = max(0, timestamp - self.env.now)
            if wait_time > 0:
                yield self.env.timeout(wait_time)
            
            # Output input event
            output_event(self.env.now, "input_reader1", "input", {
                "valid": valid,
                "invalid": invalid
            })
            
            # Forward to AAM with 10 second delay
            yield self.env.timeout(10.0)
            self.aam.process_request(valid, invalid, self.env.now)


class AAM:
    """Account Access Manager - handles login requests."""
    
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
        
    def process_request(self, valid, invalid, arrival_time):
        """Process a login request."""
        # Check if valid=1 and invalid=0 -> forward to ANV
        # Check if valid=1 and invalid=1 -> logout
        if valid == 1 and invalid == 0:
            # Valid login - forward to ANV
            output_event(self.env.now, "AAM1", "account_generated", {})
            # Forward to ANV with 10 second delay
            self.env.process(self._forward_to_anv())
        elif valid == 1 and invalid == 1:
            # Invalid login - logout
            output_event(self.env.now, "AAM1", "logout", {})
    
    def _forward_to_anv(self):
        """Forward to ANV with delay."""
        yield self.env.timeout(10.0)
        self.anv.verify_account(self.env.now)


class ANV:
    """Account Number Verifier - performs random verification."""
    
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
        
    def verify_account(self, arrival_time):
        """Verify account number with 50% pass/fail."""
        # 50% chance pass, 50% chance fail
        pass_result = 1 if random.random() < 0.5 else 0
        fail_result = 0 if pass_result == 1 else 1
        
        # Output verification event
        output_event(self.env.now, "ANV1", "verification", {
            "pass": pass_result,
            "fail": fail_result
        })
        
        if pass_result == 1:
            # Pass - forward to PV with 10 second delay
            self.env.process(self._forward_to_pv())
        else:
            # Fail - end processing
            pass
    
    def _forward_to_pv(self):
        """Forward to PV with delay."""
        yield self.env.timeout(10.0)
        self.pv.verify_password(self.env.now)


class PV:
    """Password Verifier - keeps trying until success."""
    
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm
        
    def verify_password(self, arrival_time):
        """Verify password with 50% success per attempt."""
        attempts = 0
        success = 0
        
        # Keep trying until success (50% chance each attempt)
        while success == 0:
            attempts += 1
            success = 1 if random.random() < 0.5 else 0
        
        # Output verification event
        output_event(self.env.now, "PV1", "verification", {
            "success": success,
            "attempts": attempts
        })
        
        # Forward to BPM with 10 second delay
        self.env.process(self._forward_to_bpm())
    
    def _forward_to_bpm(self):
        """Forward to BPM with delay."""
        yield self.env.timeout(10.0)
        self.bpm.generate_bill(self.env.now)


class BPM:
    """Bill Payment Manager - generates random bill amounts."""
    
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
        
    def generate_bill(self, arrival_time):
        """Generate a random bill amount (0-40), constrained by remaining balance."""
        remaining_balance = self.tpm.get_remaining_balance()
        
        # Generate random amount between 0 and 40, but not exceeding remaining balance
        max_amount = min(40, remaining_balance)
        amount = random.randint(0, max_amount)
        
        # Output bill event
        output_event(self.env.now, "BPM1", "bill", {
            "amount": amount
        })
        
        # Forward to TPM with 10 second delay
        self.env.process(self._forward_to_tpm(amount))
    
    def _forward_to_tpm(self, amount):
        """Forward to TPM with delay."""
        yield self.env.timeout(10.0)
        self.tpm.process_transaction(amount, self.env.now)


class TPM:
    """Transaction Process Manager - processes transactions and tracks balance."""
    
    def __init__(self, env):
        self.env = env
        self.balance = 3000
        self.count = 0
        
    def get_remaining_balance(self):
        """Get the current remaining balance."""
        return self.balance
    
    def process_transaction(self, amount, arrival_time):
        """Process a transaction and update balance."""
        # Calculate remaining balance
        self.balance = self.balance - amount
        self.count += 1
        
        # Output transaction event
        output_event(self.env.now, "TPM1", "transaction", {
            "remaining": self.balance,
            "count": self.count
        })


def main():
    """Main entry point for the simulation."""
    parser = argparse.ArgumentParser(description='IOBS Discrete Event Simulation')
    parser.add_argument(
        '--simulation_time',
        type=float,
        default=1000000.0,
        help='Total simulation time in seconds'
    )
    args = parser.parse_args()
    
    logger.info(f"Starting IOBS simulation with max time: {args.simulation_time}")
    
    # Create simpy environment
    env = simpy.Environment()
    
    # Create TPM (Transaction Process Manager)
    tpm = TPM(env)
    
    # Create BPM (Bill Payment Manager)
    bpm = BPM(env, tpm)
    
    # Create PV (Password Verifier)
    pv = PV(env, bpm)
    
    # Create ANV (Account Number Verifier)
    anv = ANV(env, pv)
    
    # Create AAM (Account Access Manager)
    aam = AAM(env, anv)
    
    # Create Input Reader
    input_reader = InputReader(env, aam)
    
    # Load requests from stdin
    input_reader.load_requests()
    logger.info(f"Loaded {len(input_reader.requests)} requests")
    
    # Start the input reader process
    env.process(input_reader.process())
    
    # Run the simulation
    logger.info("Running simulation...")
    env.run(until=args.simulation_time)
    
    logger.info("Simulation completed")


if __name__ == "__main__":
    main()
