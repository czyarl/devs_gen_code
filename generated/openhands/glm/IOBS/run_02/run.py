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
    """Parse timestamp string HH:MM:SS:mmm to seconds"""
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
    
    def __init__(self, env, aam):
        self.env = env
        self.aam = aam
        self.processing_delay = 10.0
    
    def run(self):
        """Main process for input reader"""
        output_event(0.0, "input_reader1", "start", {})
        
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split()
            if len(parts) < 3:
                continue
            
            timestamp_str = parts[0]
            valid = int(parts[1])
            invalid = int(parts[2])
            
            timestamp = parse_timestamp(timestamp_str)
            
            # Wait until the timestamp (only if it's in the future)
            if timestamp > self.env.now:
                yield self.env.timeout(timestamp - self.env.now)
            
            # Output input event
            output_event(self.env.now, "input_reader1", "input", {
                "valid": valid,
                "invalid": invalid
            })
            
            # Processing delay
            yield self.env.timeout(self.processing_delay)
            
            # Forward to AAM
            self.env.process(self.aam.process_request(valid, invalid))


class AAM:
    """Account Access Manager"""
    
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
        self.processing_delay = 10.0
    
    def process_request(self, valid, invalid):
        """Process login request"""
        # Processing delay
        yield self.env.timeout(self.processing_delay)
        
        if valid == 1 and invalid == 0:
            # Valid login - forward to ANV
            output_event(self.env.now, "AAM1", "account_generated", {})
            self.env.process(self.anv.verify_account())
        elif valid == 1 and invalid == 1:
            # Invalid login - trigger logout
            output_event(self.env.now, "AAM1", "logout", {})


class ANV:
    """Account Number Verifier"""
    
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
        self.processing_delay = 10.0
    
    def verify_account(self):
        """Verify account number - 50% pass, 50% fail"""
        # Processing delay
        yield self.env.timeout(self.processing_delay)
        
        # Random verification: 50% pass, 50% fail
        if random.random() < 0.5:
            # Pass
            output_event(self.env.now, "ANV1", "verification", {
                "pass": 1,
                "fail": 0
            })
            # Forward to PV
            self.env.process(self.pv.verify_password())
        else:
            # Fail
            output_event(self.env.now, "ANV1", "verification", {
                "pass": 0,
                "fail": 1
            })


class PV:
    """Password Verifier"""
    
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm
        self.processing_delay = 10.0
    
    def verify_password(self):
        """Verify password - keeps trying until success (50% per attempt)"""
        attempts = 0
        
        while True:
            attempts += 1
            # Processing delay for each attempt
            yield self.env.timeout(self.processing_delay)
            
            # 50% chance of success per attempt
            if random.random() < 0.5:
                # Success
                output_event(self.env.now, "PV1", "verification", {
                    "success": 1,
                    "attempts": attempts
                })
                # Forward to BPM
                self.env.process(self.bpm.generate_bill())
                break


class BPM:
    """Bill Payment Manager"""
    
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
        self.processing_delay = 10.0
    
    def generate_bill(self):
        """Generate random bill amount (0-40, constrained by remaining balance)"""
        # Processing delay
        yield self.env.timeout(self.processing_delay)
        
        # Get remaining balance from TPM
        remaining_balance = self.tpm.get_remaining_balance()
        
        # Generate random amount between 0 and 40, constrained by remaining balance
        max_amount = min(40, remaining_balance)
        amount = random.randint(0, max_amount)
        
        output_event(self.env.now, "BPM1", "bill", {
            "amount": amount
        })
        
        # Forward to TPM
        self.env.process(self.tpm.process_transaction(amount))


class TPM:
    """Transaction Process Manager"""
    
    def __init__(self, env):
        self.env = env
        self.balance = 3000
        self.transaction_count = 0
        self.processing_delay = 10.0
    
    def get_remaining_balance(self):
        """Get current remaining balance"""
        return self.balance
    
    def process_transaction(self, amount):
        """Process transaction and update balance"""
        # Processing delay
        yield self.env.timeout(self.processing_delay)
        
        # Calculate remaining balance
        self.balance -= amount
        self.transaction_count += 1
        
        output_event(self.env.now, "TPM1", "transaction", {
            "remaining": self.balance,
            "count": self.transaction_count
        })


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Internet Online Banking System (IOBS) - Discrete Event Simulation'
    )
    parser.add_argument(
        '--simulation_time',
        type=float,
        default=1000000.0,
        help='Total simulation time in seconds'
    )
    args = parser.parse_args()
    
    logger.info(f"Starting IOBS simulation with max time: {args.simulation_time}s")
    
    # Create simpy environment
    env = simpy.Environment()
    
    # Create TPM first (no dependencies)
    tpm = TPM(env)
    
    # Create BPM (depends on TPM)
    bpm = BPM(env, tpm)
    
    # Create PV (depends on BPM)
    pv = PV(env, bpm)
    
    # Create ANV (depends on PV)
    anv = ANV(env, pv)
    
    # Create AAM (depends on ANV)
    aam = AAM(env, anv)
    
    # Create InputReader (depends on AAM)
    input_reader = InputReader(env, aam)
    
    # Start the input reader process
    env.process(input_reader.run())
    
    # Run simulation
    logger.info("Running simulation...")
    env.run(until=args.simulation_time)
    
    logger.info(f"Simulation completed at time: {env.now}s")
    logger.info(f"Final balance: {tpm.balance}, Total transactions: {tpm.transaction_count}")


if __name__ == '__main__':
    main()