```python
import argparse
import sys
import json
import logging
import time
import random
from collections import deque
import simpy

# Set seed for reproducibility
random.seed(time.time_ns())

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)

class Event:
    def __init__(self, time, model, event, data):
        self.time = time
        self.model = model
        self.event = event
        self.data = data

    def to_json(self):
        return json.dumps({
            "time": self.time,
            "model": self.model,
            "event": self.event,
            "data": self.data
        })

class InputReader:
    def __init__(self, env, output_queue):
        self.env = env
        self.output_queue = output_queue
        self.process = env.process(self.run())

    def run(self):
        # Emit start event at t=0
        yield self.env.timeout(0)
        start_event = Event(self.env.now, "input_reader1", "start", {})
        self.output_queue.append(start_event)
        print(start_event.to_json(), file=sys.stdout)
        
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
                # Convert to simulation time (seconds)
                sim_time = h * 3600 + m * 60 + s + ms / 1000.0
                
                # Wait until the event time
                yield self.env.timeout(sim_time - self.env.now)
                
                # Emit input event
                input_event = Event(self.env.now, "input_reader1", "input", {"valid": valid, "invalid": invalid})
                self.output_queue.append(input_event)
                print(input_event.to_json(), file=sys.stdout)
                
                # Pass to AAM
                aam_event = Event(self.env.now, "AAM1", "account_received", {"valid": valid, "invalid": invalid})
                self.output_queue.append(aam_event)
                print(aam_event.to_json(), file=sys.stdout)
                
            except Exception as e:
                logging.error(f"Error processing input line: {line} - {e}")

class AAM:
    def __init__(self, env, input_queue, output_queue):
        self.env = env
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.process = env.process(self.run())

    def run(self):
        while True:
            # Wait for an event
            if not self.input_queue:
                yield self.env.timeout(1)  # Wait a bit to prevent busy waiting
                continue
                
            event = self.input_queue.popleft()
            
            # Process after 10 seconds
            yield self.env.timeout(10)
            
            if event.event == "account_received":
                valid = event.data["valid"]
                invalid = event.data["invalid"]
                
                if valid == 1 and invalid == 0:
                    # Valid login, forward to ANV
                    account_event = Event(self.env.now, "AAM1", "account_generated", {})
                    self.output_queue.append(account_event)
                    print(account_event.to_json(), file=sys.stdout)
                    
                    # Forward to ANV
                    anv_event = Event(self.env.now, "ANV1", "account_received", {"account": "account_123"})
                    self.output_queue.append(anv_event)
                    print(anv_event.to_json(), file=sys.stdout)
                elif valid == 1 and invalid == 1:
                    # Invalid login, trigger logout
                    logout_event = Event(self.env.now, "AAM1", "logout", {})
                    self.output_queue.append(logout_event)
                    print(logout_event.to_json(), file=sys.stdout)

class ANV:
    def __init__(self, env, input_queue, output_queue):
        self.env = env
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.process = env.process(self.run())

    def run(self):
        while True:
            # Wait for an event
            if not self.input_queue:
                yield self.env.timeout(1)  # Wait a bit to prevent busy waiting
                continue
                
            event = self.input_queue.popleft()
            
            # Process after 10 seconds
            yield self.env.timeout(10)
            
            if event.event == "account_received":
                # 50% chance pass, 50% chance fail
                passed = random.choice([True, False])
                pass_val = 1 if passed else 0
                fail_val = 1 if not passed else 0
                
                verification_event = Event(self.env.now, "ANV1", "verification", {"pass": pass_val, "fail": fail_val})
                self.output_queue.append(verification_event)
                print(verification_event.to_json(), file=sys.stdout)
                
                if passed:
                    # Forward to PV
                    pv_event = Event(self.env.now, "PV1", "account_verified", {"account": "account_123"})
                    self.output_queue.append(pv_event)
                    print(pv_event.to_json(), file=sys.stdout)
                else:
                    # End processing
                    pass

class PV:
    def __init__(self, env, input_queue, output_queue):
        self.env = env
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.attempts = 0
        self.process = env.process(self.run())

    def run(self):
        while True:
            # Wait for an event
            if not self.input_queue:
                yield self.env.timeout(1)  # Wait a bit to prevent busy waiting
                continue
                
            event = self.input_queue.popleft()
            
            # Process after 10 seconds
            yield self.env.timeout(10)
            
            if event.event == "account_verified":
                # Keep trying until success (50% chance per attempt)
                success = False
                attempts = 0
                while not success:
                    attempts += 1
                    success = random.choice([True, False])
                    if success:
                        break
                    yield self.env.timeout(10)  # Wait 10 seconds before next attempt
                
                # When success, emit verification event
                verification_event = Event(self.env.now, "PV1", "verification", {"success": 1, "attempts": attempts})
                self.output_queue.append(verification_event)
                print(verification_event.to_json(), file=sys.stdout)
                
                # Forward to BPM
                bpm_event = Event(self.env.now, "BPM1", "payment_ready", {"account": "account_123"})
                self.output_queue.append(bpm_event)
                print(bpm_event.to_json(), file=sys.stdout)

class BPM:
    def __init__(self, env, input_queue, output_queue):
        self.env = env
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.process = env.process(self.run())

    def run(self):
        while True:
            # Wait for an event
            if not self.input_queue:
                yield self.env.timeout(1)  # Wait a bit to prevent busy waiting
                continue
                
            event = self.input_queue.popleft()
            
            # Process after 10 seconds
            yield self.env.timeout(10)
            
            if event.event == "payment_ready":
                # Generate random bill amount between 0 and 40
                amount = random.randint(0, 40)
                
                bill_event = Event(self.env.now, "BPM1", "bill", {"amount": amount})
                self.output_queue.append(bill_event)
                print(bill_event.to_json(), file=sys.stdout)
                
                # Forward to TPM
                tpm_event = Event(self.env.now, "TPM1", "transaction_init", {"amount": amount})
                self.output_queue.append(tpm_event)
                print(tpm_event.to_json(), file=sys.stdout)

class TPM:
    def __init__(self, env, input_queue, output_queue):
        self.env = env
        self.input_queue = input_queue
        self.output_queue = output_queue
        self.balance = 3000
        self.transaction_count = 0
        self.process = env.process(self.run())

    def run(self):
        while True:
            # Wait for an event
            if not self.input_queue:
                yield self.env.timeout(1)  # Wait a bit to prevent busy waiting
                continue
                
            event = self.input_queue.popleft()
            
            # Process after 10 seconds
            yield self.env.timeout(10)
            
            if event.event == "transaction_init":
                amount = event.data["amount"]
                
                # Ensure bill amount doesn't exceed balance
                if amount > self.balance:
                    amount = self.balance
                
                # Deduct amount from balance
                self.balance -= amount
                self.transaction_count += 1
                
                # Emit transaction event
                transaction_event = Event(self.env.now, "TPM1", "transaction", {"remaining": self.balance, "count": self.transaction_count})
                self.output_queue.append(transaction_event)
                print(transaction_event.to_json(), file=sys.stdout)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulation_time', type=float, default=1000000.0)
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create queues for communication between entities
    input_queue = deque()
    output_queue = deque()
    
    # Create entities
    input_reader = InputReader(env, output_queue)
    aam = AAM(env, input_queue, output_queue)
    anv = ANV(env, input_queue, output_queue)
    pv = PV(env, input_queue, output_queue)
    bpm = BPM(env, input_queue, output_queue)
    tpm = TPM(env, input_queue, output_queue)
    
    # Run simulation for specified time
    env.run(until=args.simulation_time)
    
    # Output any remaining events in the queue
    while output_queue:
        event = output_queue.popleft()
        print(event.to_json(), file=sys.stdout)

if __name__ == "__main__":
    main()
</python_code>