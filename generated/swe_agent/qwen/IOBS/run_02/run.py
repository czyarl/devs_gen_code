#!/usr/bin/env python3
"""
Discrete Event Simulation for Internet Online Banking System (IOBS)
"""

import argparse
import sys
import json
import logging
import time
import random
import simpy

# Set up logging to stderr
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)

class InputReader1:
    """Reads input from stdin and forwards to AAM"""
    
    def __init__(self, env, aam):
        self.env = env
        self.aam = aam
        self.process = env.process(self._run())
        
    def _run(self):
        # Emit start event at t=0
        yield self.env.timeout(0)
        event_data = {
            "time": self.env.now,
            "model": "input_reader1",
            "event": "start",
            "data": {}
        }
        print(json.dumps(event_data))
        logging.info(f"input_reader1 start event at time {self.env.now}")
        
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
                
                # Convert timestamp to seconds
                hours, minutes, seconds, milliseconds = map(int, timestamp_str.split(':'))
                timestamp = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
                
                # Wait until the timestamp
                yield self.env.timeout(timestamp - self.env.now)
                
                # Emit input event
                event_data = {
                    "time": self.env.now,
                    "model": "input_reader1",
                    "event": "input",
                    "data": {
                        "valid": valid,
                        "invalid": invalid
                    }
                }
                print(json.dumps(event_data))
                logging.info(f"input_reader1 input event at time {self.env.now}")
                
                # Forward to AAM
                self.aam.handle_request(valid, invalid)
                
            except Exception as e:
                logging.error(f"Error processing input line '{line}': {e}")

class AAM1:
    """Account Access Manager"""
    
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
        self.request_queue = simpy.Store(env)
        self.process = env.process(self._run())
        
    def _run(self):
        while True:
            # Wait for a request
            valid, invalid = yield self.request_queue.get()
            
            # Process based on validity
            if valid == 1 and invalid == 0:
                # Valid login - forward to ANV
                yield self.env.timeout(10)  # 10 second delay
                
                event_data = {
                    "time": self.env.now,
                    "model": "AAM1",
                    "event": "account_generated",
                    "data": {}
                }
                print(json.dumps(event_data))
                logging.info(f"AAM1 account_generated event at time {self.env.now}")
                
                # Forward to ANV
                self.anv.handle_request()
                
            elif valid == 1 and invalid == 1:
                # Invalid login - trigger logout
                yield self.env.timeout(10)  # 10 second delay
                
                event_data = {
                    "time": self.env.now,
                    "model": "AAM1",
                    "event": "logout",
                    "data": {}
                }
                print(json.dumps(event_data))
                logging.info(f"AAM1 logout event at time {self.env.now}")
                
    def handle_request(self, valid, invalid):
        # Put request in queue
        self.request_queue.put((valid, invalid))

class ANV1:
    """Account Number Verifier"""
    
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
        self.request_queue = simpy.Store(env)
        self.process = env.process(self._run())
        
    def _run(self):
        while True:
            # Wait for a request
            yield self.request_queue.get()
            
            # 50% chance pass, 50% chance fail
            passed = random.random() < 0.5
            
            yield self.env.timeout(10)  # 10 second delay
            
            event_data = {
                "time": self.env.now,
                "model": "ANV1",
                "event": "verification",
                "data": {
                    "pass": 1 if passed else 0,
                    "fail": 1 if not passed else 0
                }
            }
            print(json.dumps(event_data))
            logging.info(f"ANV1 verification event at time {self.env.now}")
            
            if passed:
                # Forward to PV
                self.pv.handle_request()
            # If failed, processing ends here
                
    def handle_request(self):
        # Put request in queue
        self.request_queue.put(None)

class PV1:
    """Password Verifier"""
    
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm
        self.request_queue = simpy.Store(env)
        self.process = env.process(self._run())
        
    def _run(self):
        while True:
            # Wait for a request
            yield self.request_queue.get()
            
            attempts = 0
            success = False
            
            # Keep trying until success (50% chance per attempt)
            while not success:
                attempts += 1
                success = random.random() < 0.5
                if not success:
                    # Wait for another attempt (10 seconds delay)
                    yield self.env.timeout(10)
            
            yield self.env.timeout(10)  # 10 second delay for processing
            
            event_data = {
                "time": self.env.now,
                "model": "PV1",
                "event": "verification",
                "data": {
                    "success": 1,
                    "attempts": attempts
                }
            }
            print(json.dumps(event_data))
            logging.info(f"PV1 verification event at time {self.env.now}")
            
            # Forward to BPM
            self.bpm.handle_request(attempts)
            
    def handle_request(self):
        # Put request in queue
        self.request_queue.put(None)

class BPM1:
    """Bill Payment Manager"""
    
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
        self.request_queue = simpy.Store(env)
        self.process = env.process(self._run())
        
    def _run(self):
        while True:
            # Wait for a request
            attempts = yield self.request_queue.get()
            
            # Generate random bill amount between 0 and 40
            amount = random.randint(0, 40)
            
            yield self.env.timeout(10)  # 10 second delay
            
            event_data = {
                "time": self.env.now,
                "model": "BPM1",
                "event": "bill",
                "data": {
                    "amount": amount
                }
            }
            print(json.dumps(event_data))
            logging.info(f"BPM1 bill event at time {self.env.now}")
            
            # Forward to TPM
            self.tpm.handle_request(amount)
            
    def handle_request(self, attempts):
        # Put request in queue
        self.request_queue.put(attempts)

class TPM1:
    """Transaction Process Manager"""
    
    def __init__(self, env):
        self.env = env
        self.balance = 3000
        self.transaction_count = 0
        self.request_queue = simpy.Store(env)
        self.process = env.process(self._run())
        
    def _run(self):
        while True:
            # Wait for a request
            amount = yield self.request_queue.get()
            
            # Calculate remaining balance
            self.balance -= amount
            self.transaction_count += 1
            
            yield self.env.timeout(10)  # 10 second delay
            
            event_data = {
                "time": self.env.now,
                "model": "TPM1",
                "event": "transaction",
                "data": {
                    "remaining": self.balance,
                    "count": self.transaction_count
                }
            }
            print(json.dumps(event_data))
            logging.info(f"TPM1 transaction event at time {self.env.now}")
            
    def handle_request(self, amount):
        # Put request in queue
        self.request_queue.put(amount)

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='IOBS Discrete Event Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0, 
                       help='Total simulation time in seconds (default: 1000000.0)')
    
    args = parser.parse_args()
    
    # Set random seed using system time
    random.seed(time.time_ns())
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create entities
    anv = ANV1(env, None)  # Will be updated later
    pv = PV1(env, None)    # Will be updated later
    bpm = BPM1(env, None)  # Will be updated later
    tpm = TPM1(env)
    
    # Set up the chain
    aam = AAM1(env, anv)
    anv.pv = pv
    pv.bpm = bpm
    bpm.tpm = tpm
    
    # Create input reader
    input_reader = InputReader1(env, aam)
    
    # Run simulation
    logging.info(f"Starting simulation with max time {args.simulation_time}")
    env.run(until=args.simulation_time)
    logging.info("Simulation completed")

if __name__ == "__main__":
    main()