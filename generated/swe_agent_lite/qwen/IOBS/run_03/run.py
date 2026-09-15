#!/usr/bin/env python3
"""
Internet Online Banking System (IOBS) - Discrete Event Simulation
"""

import argparse
import sys
import json
import logging
import collections
import random
import time
import simpy

# Set random seed using system time
random.seed(time.time_ns())

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Define the simulation time
SIMULATION_TIME = 10.0  # 10 seconds as per requirement

class InputReader1:
    """Reads input from stdin and forwards to AAM"""
    
    def __init__(self, env, aam):
        self.env = env
        self.aam = aam
        self.name = "input_reader1"
        
    def start(self):
        """Start reading input from stdin"""
        # Emit start event
        self.emit_event("start", {})
        
        # Read input from stdin
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
                
            try:
                # Parse timestamp and flags
                timestamp_str, valid_str, invalid_str = line.split()
                valid = int(valid_str)
                invalid = int(invalid_str)
                
                # Emit input event
                self.emit_event("input", {"valid": valid, "invalid": invalid})
                
                # Forward to AAM with delay
                self.env.process(self.forward_to_aam(valid, invalid))
                
            except Exception as e:
                logger.error(f"Error parsing input line '{line}': {e}")
                
    def forward_to_aam(self, valid, invalid):
        """Forward request to AAM after processing delay"""
        yield self.env.timeout(10.0)  # 10 seconds processing delay
        if self.aam:
            self.aam.receive_input(valid, invalid)
            
    def emit_event(self, event, data):
        """Emit an event to stdout"""
        event_obj = {
            "time": self.env.now,
            "model": self.name,
            "event": event,
            "data": data
        }
        print(json.dumps(event_obj))

class AAM1:
    """Account Access Manager"""
    
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
        self.name = "AAM1"
        
    def receive_input(self, valid, invalid):
        """Receive input from input_reader1"""
        # Emit account_generated or logout event based on validity
        if valid == 1 and invalid == 0:
            # Valid login
            self.emit_event("account_generated", {})
            # Forward to ANV after delay
            self.env.process(self.forward_to_anv())
        elif valid == 1 and invalid == 1:
            # Invalid login
            self.emit_event("logout", {})
            
    def forward_to_anv(self):
        """Forward to ANV after processing delay"""
        yield self.env.timeout(10.0)  # 10 seconds processing delay
        if self.anv:
            self.anv.receive_account()
            
    def emit_event(self, event, data):
        """Emit an event to stdout"""
        event_obj = {
            "time": self.env.now,
            "model": self.name,
            "event": event,
            "data": data
        }
        print(json.dumps(event_obj))

class ANV1:
    """Account Number Verifier"""
    
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
        self.name = "ANV1"
        
    def receive_account(self):
        """Receive account from AAM"""
        # Perform random verification (50% chance pass, 50% chance fail)
        pass_verification = random.choice([True, False])
        
        # Emit verification event
        self.emit_event("verification", {"pass": 1 if pass_verification else 0, "fail": 1 if not pass_verification else 0})
        
        # Forward to PV if passed, otherwise end processing
        if pass_verification:
            self.env.process(self.forward_to_pv())
        else:
            # End processing for this request
            pass
            
    def forward_to_pv(self):
        """Forward to PV after processing delay"""
        yield self.env.timeout(10.0)  # 10 seconds processing delay
        if self.pv:
            self.pv.receive_verification()
            
    def emit_event(self, event, data):
        """Emit an event to stdout"""
        event_obj = {
            "time": self.env.now,
            "model": self.name,
            "event": event,
            "data": data
        }
        print(json.dumps(event_obj))

class PV1:
    """Password Verifier"""
    
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm
        self.attempts = 0
        self.name = "PV1"
        
    def receive_verification(self):
        """Receive verification from ANV"""
        # Perform random password check (50% chance success per attempt)
        success = False
        self.attempts = 0
        
        # Keep trying until success
        while not success:
            self.attempts += 1
            success = random.choice([True, False])
            
        # Emit verification event
        self.emit_event("verification", {"success": 1, "attempts": self.attempts})
        
        # Forward to BPM after delay
        self.env.process(self.forward_to_bpm())
        
    def forward_to_bpm(self):
        """Forward to BPM after processing delay"""
        yield self.env.timeout(10.0)  # 10 seconds processing delay
        if self.bpm:
            self.bpm.receive_password_success()
            
    def emit_event(self, event, data):
        """Emit an event to stdout"""
        event_obj = {
            "time": self.env.now,
            "model": self.name,
            "event": event,
            "data": data
        }
        print(json.dumps(event_obj))

class BPM1:
    """Bill Payment Manager"""
    
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
        self.balance = 3000  # Initial balance
        self.name = "BPM1"
        
    def receive_password_success(self):
        """Receive password success from PV"""
        # Generate random bill amount between 0 and 40
        amount = random.randint(0, 40)
        
        # Make sure it doesn't exceed remaining account balance
        if amount > self.balance:
            amount = self.balance
            
        # Update balance
        self.balance -= amount
        
        # Emit bill event
        self.emit_event("bill", {"amount": amount})
        
        # Forward to TPM after delay
        self.env.process(self.forward_to_tpm(amount))
        
    def forward_to_tpm(self, amount):
        """Forward to TPM after processing delay"""
        yield self.env.timeout(10.0)  # 10 seconds processing delay
        if self.tpm:
            self.tpm.receive_bill(amount)
            
    def emit_event(self, event, data):
        """Emit an event to stdout"""
        event_obj = {
            "time": self.env.now,
            "model": self.name,
            "event": event,
            "data": data
        }
        print(json.dumps(event_obj))

class TPM1:
    """Transaction Process Manager"""
    
    def __init__(self, env):
        self.env = env
        self.balance = 3000  # Initial balance
        self.transaction_count = 0
        self.name = "TPM1"
        
    def receive_bill(self, amount):
        """Receive bill amount from BPM"""
        # Calculate remaining balance
        remaining = self.balance - amount
        self.balance = remaining
        self.transaction_count += 1
        
        # Emit transaction event
        self.emit_event("transaction", {"remaining": remaining, "count": self.transaction_count})
        
    def emit_event(self, event, data):
        """Emit an event to stdout"""
        event_obj = {
            "time": self.env.now,
            "model": self.name,
            "event": event,
            "data": data
        }
        print(json.dumps(event_obj))

def main():
    """Main function to run the simulation"""
    parser = argparse.ArgumentParser(description="IOBS - Internet Online Banking System")
    parser.add_argument('--simulation_time', type=float, default=10.0, help='Total simulation time in seconds')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create components
    aam = AAM1(env, None)
    anv = ANV1(env, None)
    pv = PV1(env, None)
    bpm = BPM1(env, None)
    tpm = TPM1(env)
    
    # Connect components
    input_reader = InputReader1(env, aam)
    aam.anv = anv
    anv.pv = pv
    pv.bpm = bpm
    bpm.tpm = tpm
    
    # Start the simulation
    env.process(input_reader.start())
    
    # Run simulation for specified time or until completion
    env.run(until=args.simulation_time)
    
    # Print final state to stdout
    print(json.dumps({"time": env.now, "model": "TPM1", "event": "transaction", "data": {"remaining": tpm.balance, "count": tpm.transaction_count}}))

if __name__ == "__main__":
    main()