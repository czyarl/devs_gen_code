```python_code
import argparse
import sys
import json
import logging
import time
import random
import simpy

# Set seed for reproducibility
random.seed(time.time_ns())

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)

class InputReader:
    def __init__(self, env, output_queue):
        self.env = env
        self.output_queue = output_queue

    def run(self):
        # Emit start event
        yield self.env.timeout(0)
        self.output_queue.put({
            "time": self.env.now,
            "model": "input_reader1",
            "event": "start",
            "data": {}
        })
        
        # Read input from stdin
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            
            try:
                timestamp, valid, invalid = line.split()
                valid = int(valid)
                invalid = int(invalid)
                
                # Parse timestamp
                h, m, s, ms = map(int, timestamp.split(":"))
                # Convert to seconds
                time_seconds = h * 3600 + m * 60 + s + ms / 1000.0
                
                # Emit input event
                self.output_queue.put({
                    "time": time_seconds,
                    "model": "input_reader1",
                    "event": "input",
                    "data": {
                        "valid": valid,
                        "invalid": invalid
                    }
                })
                
                # Add delay to ensure proper ordering
                yield self.env.timeout(0.001)
                
            except Exception as e:
                logging.error(f"Error parsing input line '{line}': {e}")

class AAM:
    def __init__(self, env, input_queue, output_queue):
        self.env = env
        self.input_queue = input_queue
        self.output_queue = output_queue

    def run(self):
        while True:
            # Wait for input
            event = yield self.input_queue.get()
            
            # Process the event
            if event["data"]["invalid"] == 1:
                # Invalid login - trigger logout
                yield self.env.timeout(10)  # 10 seconds delay
                self.output_queue.put({
                    "time": self.env.now,
                    "model": "AAM1",
                    "event": "logout",
                    "data": {}
                })
            else:
                # Valid login - forward to ANV
                yield self.env.timeout(10)  # 10 seconds delay
                self.output_queue.put({
                    "time": self.env.now,
                    "model": "AAM1",
                    "event": "account_generated",
                    "data": {}
                })

class ANV:
    def __init__(self, env, input_queue, output_queue):
        self.env = env
        self.input_queue = input_queue
        self.output_queue = output_queue

    def run(self):
        while True:
            # Wait for input
            yield self.input_queue.get()
            
            # Simulate verification with 50% chance of pass
            yield self.env.timeout(10)  # 10 seconds delay
            pass_verification = random.random() < 0.5
            
            # Emit verification event
            self.output_queue.put({
                "time": self.env.now,
                "model": "ANV1",
                "event": "verification",
                "data": {
                    "pass": 1 if pass_verification else 0,
                    "fail": 0 if pass_verification else 1
                }
            })

class PV:
    def __init__(self, env, input_queue, output_queue):
        self.env = env
        self.input_queue = input_queue
        self.output_queue = output_queue

    def run(self):
        while True:
            # Wait for input
            yield self.input_queue.get()
            
            # Simulate password verification with 50% chance per attempt
            attempts = 0
            success = False
            
            while not success:
                attempts += 1
                yield self.env.timeout(10)  # 10 seconds per attempt
                success = random.random() < 0.5
            
            # Emit verification event
            self.output_queue.put({
                "time": self.env.now,
                "model": "PV1",
                "event": "verification",
                "data": {
                    "success": 1,
                    "attempts": attempts
                }
            })

class BPM:
    def __init__(self, env, input_queue, output_queue, initial_balance=3000):
        self.env = env
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.balance = initial_balance

    def run(self):
        while True:
            # Wait for input
            yield self.input_queue.get()
            
            # Generate random bill amount between 0 and 40
            amount = random.randint(0, 40)
            
            # Ensure amount doesn't exceed balance
            if amount > self.balance:
                amount = self.balance
            
            # Update balance
            self.balance -= amount
            
            # Emit bill event
            self.output_queue.put({
                "time": self.env.now,
                "model": "BPM1",
                "event": "bill",
                "data": {
                    "amount": amount
                }
            })

class TPM:
    def __init__(self, env, input_queue, output_queue, initial_balance=3000):
        self.env = env
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.balance = initial_balance
        self.transaction_count = 0

    def run(self):
        while True:
            # Wait for input
            yield self.input_queue.get()
            
            # Update transaction count
            self.transaction_count += 1
            
            # Emit transaction event
            self.output_queue.put({
                "time": self.env.now,
                "model": "TPM1",
                "event": "transaction",
                "data": {
                    "remaining": self.balance,
                    "count": self.transaction_count
                }
            })

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulation_time', type=float, default=1000000.0)
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create queues for communication between components
    input_queue = simpy.Store(env)
    aam_queue = simpy.Store(env)
    anv_queue = simpy.Store(env)
    pv_queue = simpy.Store(env)
    bpm_queue = simpy.Store(env)
    tpm_queue = simpy.Store(env)
    
    # Create components
    input_reader = InputReader(env, input_queue)
    aam = AAM(env, input_queue, aam_queue)
    anv = ANV(env, aam_queue, anv_queue)
    pv = PV(env, anv_queue, pv_queue)
    bpm = BPM(env, pv_queue, bpm_queue)
    tpm = TPM(env, bpm_queue, tpm_queue)
    
    # Start all processes
    env.process(input_reader.run())
    env.process(aam.run())
    env.process(anv.run())
    env.process(pv.run())
    env.process(bpm.run())
    env.process(tpm.run())
    
    # Run simulation
    env.run(until=args.simulation_time)
    
    # Output all events that have been generated
    while not tpm_queue.empty():
        event = tpm_queue.get_nowait()
        print(json.dumps(event))

if __name__ == "__main__":
    main()
</python_code>
```