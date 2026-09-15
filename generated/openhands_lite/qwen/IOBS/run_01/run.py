#!/usr/bin/env python3
"""
Discrete Event Simulation for Internet Online Banking System (IOBS)
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

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def parse_timestamp(timestamp_str):
    """Parse timestamp string HH:MM:SS:mmm into seconds"""
    try:
        h, m, s, ms = map(int, timestamp_str.split(':'))
        return h * 3600 + m * 60 + s + ms / 1000.0
    except Exception as e:
        logger.error(f"Error parsing timestamp {timestamp_str}: {e}")
        return 0.0

class InputReader:
    """Reads input from stdin and forwards to AAM"""
    
    def __init__(self, env, aam):
        self.env = env
        self.aam = aam
        self.process = env.process(self.run())
        
    def run(self):
        """Process input from stdin"""
        # Emit start event at t=0
        print(json.dumps({
            "time": 0.0,
            "model": "input_reader1",
            "event": "start",
            "data": {}
        }))
        
        # Process each line of input
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
                
            try:
                parts = line.split()
                if len(parts) != 3:
                    logger.warning(f"Invalid input line: {line}")
                    continue
                    
                timestamp_str, valid_str, invalid_str = parts
                timestamp = parse_timestamp(timestamp_str)
                valid = int(valid_str)
                invalid = int(invalid_str)
                
                # Emit input event
                print(json.dumps({
                    "time": timestamp,
                    "model": "input_reader1",
                    "event": "input",
                    "data": {
                        "valid": valid,
                        "invalid": invalid
                    }
                }))
                
                # Forward to AAM (this will be handled by AAM's process)
                self.aam.handle_input(valid, invalid, timestamp)
                
            except Exception as e:
                logger.error(f"Error processing input line '{line}': {e}")
                continue

class AAM:
    """Account Access Manager"""
    
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
        self.process = env.process(self.run())
        
    def handle_input(self, valid, invalid, timestamp):
        """Handle input from input_reader1"""
        # Process based on validity
        if valid == 1 and invalid == 0:
            # Valid login - forward to ANV after 10 seconds
            self.env.process(self._process_valid_login(timestamp))
        elif valid == 1 and invalid == 1:
            # Invalid login - trigger logout
            self.env.process(self._process_invalid_login(timestamp))
    
    def _process_valid_login(self, timestamp):
        """Process valid login"""
        yield self.env.timeout(10)
        print(json.dumps({
            "time": timestamp + 10.0,
            "model": "AAM1",
            "event": "account_generated",
            "data": {}
        }))
        # Forward to ANV
        self.anv.handle_account(timestamp + 10.0)
    
    def _process_invalid_login(self, timestamp):
        """Process invalid login"""
        yield self.env.timeout(10)
        print(json.dumps({
            "time": timestamp + 10.0,
            "model": "AAM1",
            "event": "logout",
            "data": {}
        }))

    def run(self):
        """Main process for AAM"""
        # This is a placeholder - actual processing happens in handle_input
        pass

class ANV:
    """Account Number Verifier"""
    
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
        self.process = env.process(self.run())
        
    def handle_account(self, timestamp):
        """Handle account from AAM"""
        # Process with 50% chance of passing
        self.env.process(self._process_account(timestamp))
    
    def _process_account(self, timestamp):
        yield self.env.timeout(10)
        pass_result = random.choice([0, 1])  # 50% chance
        
        print(json.dumps({
            "time": timestamp + 10.0,
            "model": "ANV1",
            "event": "verification",
            "data": {
                "pass": pass_result,
                "fail": 1 - pass_result
            }
        }))
        
        if pass_result:
            # Forward to PV
            self.pv.handle_verification(timestamp + 10.0)
        # If fail, processing ends here

    def run(self):
        """Main process for ANV"""
        # This is a placeholder - actual processing happens in handle_account
        pass

class PV:
    """Password Verifier"""
    
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm
        self.process = env.process(self.run())
        
    def handle_verification(self, timestamp):
        """Handle verification from ANV"""
        self.env.process(self._process_verification(timestamp))
    
    def _process_verification(self, timestamp):
        """Process password verification with retries"""
        attempts = 0
        
        # Keep trying until success (50% chance per attempt)
        success = False
        while not success:
            attempts += 1
            success = random.choice([0, 1])  # 50% chance of success
            if not success:
                yield self.env.timeout(10)  # Wait 10 seconds before next attempt
        
        # Success - forward to BPM
        yield self.env.timeout(10)
        print(json.dumps({
            "time": timestamp + 10.0,
            "model": "PV1",
            "event": "verification",
            "data": {
                "success": 1,
                "attempts": attempts
            }
        }))
        self.bpm.handle_password_success(timestamp + 10.0)

    def run(self):
        """Main process for PV"""
        # This is a placeholder - actual processing happens in handle_verification
        pass

class BPM:
    """Bill Payment Manager"""
    
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
        self.process = env.process(self.run())
        self.balance = 3000  # Initial balance
        
    def handle_password_success(self, timestamp):
        """Handle password success from PV"""
        self.env.process(self._process_password_success(timestamp))
    
    def _process_password_success(self, timestamp):
        """Process password success"""
        # Generate random bill amount between 0 and 40
        amount = random.randint(0, 40)
        
        # Ensure it doesn't exceed remaining balance
        if amount > self.balance:
            amount = self.balance
            
        yield self.env.timeout(10)
        print(json.dumps({
            "time": timestamp + 10.0,
            "model": "BPM1",
            "event": "bill",
            "data": {
                "amount": amount
            }
        }))
        self.tpm.handle_bill(amount, timestamp + 10.0)

    def run(self):
        """Main process for BPM"""
        # This is a placeholder - actual processing happens in handle_password_success
        pass

class TPM:
    """Transaction Process Manager"""
    
    def __init__(self, env):
        self.env = env
        self.process = env.process(self.run())
        self.balance = 3000  # Initial balance
        self.transaction_count = 0
        
    def handle_bill(self, amount, timestamp):
        """Handle bill from BPM"""
        self.env.process(self._process_bill(amount, timestamp))
    
    def _process_bill(self, amount, timestamp):
        """Process bill"""
        self.balance -= amount
        self.transaction_count += 1
        
        yield self.env.timeout(10)
        print(json.dumps({
            "time": timestamp + 10.0,
            "model": "TPM1",
            "event": "transaction",
            "data": {
                "remaining": self.balance,
                "count": self.transaction_count
            }
        }))

    def run(self):
        """Main process for TPM"""
        # This is a placeholder - actual processing happens in handle_bill
        pass

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
    
    # Run simulation for specified time or until completion
    env.run(until=args.simulation_time)
    
    # Ensure we end the simulation properly
    print(json.dumps({
        "time": args.simulation_time,
        "model": "simulation",
        "event": "end",
        "data": {}
    }))

if __name__ == "__main__":
    main()