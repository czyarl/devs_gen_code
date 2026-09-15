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

# Set seed for reproducibility using system time
random.seed(time.time_ns())

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class IOBSModel:
    """Main IOBS model that orchestrates the simulation"""
    
    def __init__(self):
        self.balance = 3000
        self.transaction_count = 0
        
    def process_input(self, timestamp, valid, invalid):
        """Process an input request"""
        # Emit start event at t=0
        if timestamp == 0:
            print(json.dumps({
                "time": 0.0,
                "model": "input_reader1",
                "event": "start",
                "data": {}
            }), file=sys.stdout)
        
        # Emit input event
        print(json.dumps({
            "time": timestamp,
            "model": "input_reader1",
            "event": "input",
            "data": {
                "valid": valid,
                "invalid": invalid
            }
        }), file=sys.stdout)
        
        # Process based on valid/invalid flags
        if valid == 1 and invalid == 0:
            # Valid login - forward to AAM (10s delay)
            print(json.dumps({
                "time": timestamp + 10.0,
                "model": "AAM1",
                "event": "account_generated",
                "data": {}
            }), file=sys.stdout)
            
            # ANV verification (10s delay)
            self.anv_verification(timestamp + 20.0)
            
        elif valid == 1 and invalid == 1:
            # Invalid login - trigger logout (10s delay)
            print(json.dumps({
                "time": timestamp + 10.0,
                "model": "AAM1",
                "event": "logout",
                "data": {}
            }), file=sys.stdout)
    
    def anv_verification(self, timestamp):
        """Account Number Verification"""
        # Perform random verification (50% chance pass)
        pass_verification = random.choice([True, False])
        
        # Emit verification result
        print(json.dumps({
            "time": timestamp,
            "model": "ANV1",
            "event": "verification",
            "data": {
                "pass": 1 if pass_verification else 0,
                "fail": 0 if pass_verification else 1
            }
        }), file=sys.stdout)
        
        if pass_verification:
            # Forward to PV (10s delay)
            self.pv_verification(timestamp + 10.0)
        # If failed, processing ends here
    
    def pv_verification(self, timestamp):
        """Password Verification"""
        # Perform random password check (50% chance success per attempt)
        success = False
        attempts = 0
        
        # Keep trying until success
        while not success:
            attempts += 1
            success = random.choice([True, False])
            
        # Emit verification result
        print(json.dumps({
            "time": timestamp,
            "model": "PV1",
            "event": "verification",
            "data": {
                "success": 1,
                "attempts": attempts
            }
        }), file=sys.stdout)
        
        # Forward to BPM (10s delay)
        self.bpm_bill_generation(timestamp + 10.0)
        
    def bpm_bill_generation(self, timestamp):
        """Bill Payment Management"""
        # Generate random bill amount between 0 and 40
        amount = random.randint(0, 40)
        
        # Ensure it doesn't exceed remaining balance
        if amount > self.balance:
            amount = self.balance
            
        # Update balance and transaction count
        self.balance -= amount
        self.transaction_count += 1
        
        # Emit bill amount
        print(json.dumps({
            "time": timestamp,
            "model": "BPM1",
            "event": "bill",
            "data": {
                "amount": amount
            }
        }), file=sys.stdout)
        
        # Forward to TPM (10s delay)
        self.tpm_transaction(timestamp + 10.0, self.balance, self.transaction_count)
    
    def tpm_transaction(self, timestamp, balance, count):
        """Transaction Process Management"""
        # Update state
        self.balance = balance
        self.transaction_count = count
        
        # Emit transaction result
        print(json.dumps({
            "time": timestamp,
            "model": "TPM1",
            "event": "transaction",
            "data": {
                "remaining": self.balance,
                "count": self.transaction_count
            }
        }), file=sys.stdout)

def main():
    parser = argparse.ArgumentParser(description='IOBS Discrete Event Simulation')
    parser.add_argument('--simulation_time', type=float, default=100.0, 
                       help='Total simulation time in seconds')
    
    args = parser.parse_args()
    
    # Create model
    model = IOBSModel()
    
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
            
            # Process the input
            model.process_input(timestamp_seconds, valid, invalid)
            
        except Exception as e:
            logger.error(f"Error processing input line '{line}': {e}")
            continue

if __name__ == "__main__":
    main()