#!/usr/bin/env python3
"""
Internet Online Banking System (IOBS) Discrete Event Simulation
"""

import argparse
import sys
import json
import logging
import time
import random
import simpy

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)

class IOBSModel:
    def __init__(self, env):
        self.env = env
        self.input_reader1 = InputReader1(env)
        self.AAM1 = AAM1(env)
        self.ANV1 = ANV1(env)
        self.PV1 = PV1(env)
        self.BPM1 = BPM1(env)
        self.TPM1 = TPM1(env)
        
        # Connect components
        self.input_reader1.output = self.AAM1.input
        self.AAM1.output = self.ANV1.input
        self.ANV1.output = self.PV1.input
        self.PV1.output = self.BPM1.input
        self.BPM1.output = self.TPM1.input
        
        # Set up random seed using system time
        random.seed(time.time_ns())
        
    def run(self, simulation_time):
        # Start the simulation
        self.env.process(self.input_reader1.run())
        self.env.run(until=simulation_time)

class InputReader1:
    def __init__(self, env):
        self.env = env
        self.output = None  # Will be set by IOBSModel
        self.model_name = "input_reader1"
        
    def run(self):
        # Emit start event at t=0
        yield self.env.timeout(0)
        event_data = {
            "time": self.env.now,
            "model": self.model_name,
            "event": "start",
            "data": {}
        }
        print(json.dumps(event_data))
        sys.stderr.write(f"InputReader1: Start event at time {self.env.now}\n")
        
        # Process input from stdin
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
                    "model": self.model_name,
                    "event": "input",
                    "data": {
                        "valid": valid,
                        "invalid": invalid
                    }
                }
                print(json.dumps(event_data))
                sys.stderr.write(f"InputReader1: Input event at time {self.env.now}\n")
                
                # Send to next component
                yield self.output.put((valid, invalid))
                
            except Exception as e:
                sys.stderr.write(f"Error processing input line '{line}': {e}\n")
                continue

class AAM1:
    def __init__(self, env):
        self.env = env
        self.input = simpy.Store(env)
        self.output = None  # Will be set by IOBSModel
        self.model_name = "AAM1"
        
    def run(self):
        while True:
            # Wait for input
            valid, invalid = yield self.input.get()
            
            # Process the request
            if valid == 1 and invalid == 0:
                # Valid login - forward to ANV
                yield self.env.timeout(10)  # 10 second delay
                
                event_data = {
                    "time": self.env.now,
                    "model": self.model_name,
                    "event": "account_generated",
                    "data": {}
                }
                print(json.dumps(event_data))
                sys.stderr.write(f"AAM1: Account generated at time {self.env.now}\n")
                
                # Forward to ANV
                yield self.output.put(valid)
                
            elif valid == 1 and invalid == 1:
                # Invalid login - trigger logout
                yield self.env.timeout(10)  # 10 second delay
                
                event_data = {
                    "time": self.env.now,
                    "model": self.model_name,
                    "event": "logout",
                    "data": {}
                }
                print(json.dumps(event_data))
                sys.stderr.write(f"AAM1: Logout at time {self.env.now}\n")

class ANV1:
    def __init__(self, env):
        self.env = env
        self.input = simpy.Store(env)
        self.output = None  # Will be set by IOBSModel
        self.model_name = "ANV1"
        
    def run(self):
        while True:
            # Wait for input
            valid = yield self.input.get()
            
            # Perform verification (50% chance pass, 50% chance fail)
            pass_verification = random.choice([True, False])
            
            # Wait for 10 seconds processing delay
            yield self.env.timeout(10)
            
            # Emit verification event
            event_data = {
                "time": self.env.now,
                "model": self.model_name,
                "event": "verification",
                "data": {
                    "pass": 1 if pass_verification else 0,
                    "fail": 0 if pass_verification else 1
                }
            }
            print(json.dumps(event_data))
            sys.stderr.write(f"ANV1: Verification result at time {self.env.now}\n")
            
            if pass_verification:
                # Forward to PV
                yield self.output.put(valid)
            # If failed, end processing

class PV1:
    def __init__(self, env):
        self.env = env
        self.input = simpy.Store(env)
        self.output = None  # Will be set by IOBSModel
        self.model_name = "PV1"
        
    def run(self):
        while True:
            # Wait for input
            valid = yield self.input.get()
            
            # Perform password check (50% chance success per attempt)
            attempts = 0
            success = False
            
            while not success:
                attempts += 1
                success = random.choice([True, False])
                
            # Wait for 10 seconds processing delay
            yield self.env.timeout(10)
            
            # Emit verification event
            event_data = {
                "time": self.env.now,
                "model": self.model_name,
                "event": "verification",
                "data": {
                    "success": 1,
                    "attempts": attempts
                }
            }
            print(json.dumps(event_data))
            sys.stderr.write(f"PV1: Password verification at time {self.env.now}\n")
            
            # Forward to BPM
            yield self.output.put(valid)

class BPM1:
    def __init__(self, env):
        self.env = env
        self.input = simpy.Store(env)
        self.output = None  # Will be set by IOBSModel
        self.model_name = "BPM1"
        
    def run(self):
        while True:
            # Wait for input
            valid = yield self.input.get()
            
            # Wait for 10 seconds processing delay
            yield self.env.timeout(10)
            
            # Generate random bill amount between 0 and 40
            amount = random.randint(0, 40)
            
            # Emit bill event
            event_data = {
                "time": self.env.now,
                "model": self.model_name,
                "event": "bill",
                "data": {
                    "amount": amount
                }
            }
            print(json.dumps(event_data))
            sys.stderr.write(f"BPM1: Bill generated at time {self.env.now}\n")
            
            # Forward to TPM
            yield self.output.put(amount)

class TPM1:
    def __init__(self, env):
        self.env = env
        self.input = simpy.Store(env)
        self.model_name = "TPM1"
        self.balance = 3000
        self.transaction_count = 0
        
    def run(self):
        while True:
            # Wait for input
            amount = yield self.input.get()
            
            # Wait for 10 seconds processing delay
            yield self.env.timeout(10)
            
            # Calculate remaining balance
            self.balance -= amount
            self.transaction_count += 1
            
            # Emit transaction event
            event_data = {
                "time": self.env.now,
                "model": self.model_name,
                "event": "transaction",
                "data": {
                    "remaining": self.balance,
                    "count": self.transaction_count
                }
            }
            print(json.dumps(event_data))
            sys.stderr.write(f"TPM1: Transaction processed at time {self.env.now}\n")

def main():
    parser = argparse.ArgumentParser(description='IOBS Discrete Event Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0, 
                       help='Total simulation time in seconds (default: 1000000.0)')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create IOBS model
    model = IOBSModel(env)
    
    # Run simulation with 10 seconds real time constraint
    import time as time_module
    start_time = time_module.time()
    
    # Run simulation for the specified time or until 10 seconds real time has passed
    max_real_time = 10.0  # 10 seconds real time
    try:
        model.run(args.simulation_time)
    except KeyboardInterrupt:
        pass
    
    # Ensure we don't exceed 10 seconds real time
    end_time = time_module.time()
    if end_time - start_time > max_real_time:
        sys.stderr.write(f"Simulation ended due to real time constraint ({max_real_time}s)\n")

if __name__ == "__main__":
    main()