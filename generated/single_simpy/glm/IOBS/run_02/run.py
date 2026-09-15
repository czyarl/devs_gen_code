import argparse
import sys
import json
import logging
import random
import time
import simpy

# Configure logging to Standard Error
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Set random seeds using system time as requested
seed_ns = time.time_ns()
random.seed(seed_ns)

# Attempt to seed numpy if available, as per requirements
try:
    import numpy
    numpy.random.seed(seed_ns % (2**32 - 1))
except ImportError:
    pass

def log_event(time, model, event, data):
    """
    Prints a JSONL object to Standard Output.
    """
    output = {
        "time": time,
        "model": model,
        "event": event,
        "data": data
    }
    print(json.dumps(output))

class TPM:
    def __init__(self, env):
        self.env = env
        self.balance = 3000
        self.count = 0
        # Resource to handle concurrent access to the account balance safely
        self.resource = simpy.Resource(env, capacity=1)

    def process(self, amount):
        """
        Receives bill amount from BPM.
        Calculates remaining balance.
        Tracks transaction count.
        Delay: 10 seconds.
        """
        yield self.env.timeout(10)
        
        self.balance -= amount
        self.count += 1
        
        log_event(self.env.now, "TPM1", "transaction", {
            "remaining": self.balance,
            "count": self.count
        })

class BPM:
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm

    def process(self):
        """
        Receives successful password verification.
        Generates random bill amount (0-40) constrained by balance.
        Forwards to TPM.
        Delay: 10 seconds.
        """
        yield self.env.timeout(10)
        
        # Request exclusive access to TPM to ensure balance check is atomic
        with self.tpm.resource.request() as req:
            yield req
            
            # Generate amount
            # Constraint: does not exceed remaining account balance
            max_amount = min(40, self.tpm.balance)
            amount = random.randint(0, max_amount)
            
            log_event(self.env.now, "BPM1", "bill", {
                "amount": amount
            })
            
            # Forward to TPM
            # We run TPM process within the resource lock context to ensure
            # the balance isn't modified by another transaction between check and update.
            yield self.env.process(self.tpm.process(amount))

class PV:
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm

    def process(self):
        """
        Receives verification from ANV.
        Performs random password check (50% success).
        Retries until success.
        Delay: 10 seconds (total).
        """
        yield self.env.timeout(10)
        
        attempts = 0
        success = False
        while not success:
            attempts += 1
            if random.random() < 0.5:
                success = True
        
        log_event(self.env.now, "PV1", "verification", {
            "success": 1,
            "attempts": attempts
        })
        
        # Forward to BPM
        self.env.process(self.bpm.process())

class ANV:
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv

    def process(self):
        """
        Receives account from AAM.
        Performs random verification: 50% pass, 50% fail.
        Delay: 10 seconds.
        """
        yield self.env.timeout(10)
        
        passed = 1 if random.random() < 0.5 else 0
        failed = 0 if passed else 1
        
        log_event(self.env.now, "ANV1", "verification", {
            "pass": passed,
            "fail": failed
        })
        
        if passed:
            # Forward to PV
            self.env.process(self.pv.process())

class AAM:
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv

    def process(self, valid, invalid):
        """
        Receives login requests.
        If valid=1 and invalid=0: Forward to ANV.
        If valid=1 and invalid=1: Trigger logout.
        Delay: 10 seconds.
        """
        yield self.env.timeout(10)
        
        if valid == 1 and invalid == 0:
            log_event(self.env.now, "AAM1", "account_generated", {})
            # Forward to ANV
            self.env.process(self.anv.process())
        elif valid == 1 and invalid == 1:
            log_event(self.env.now, "AAM1", "logout", {})

class InputReader:
    def __init__(self, env, aam):
        self.env = env
        self.aam = aam

    def start(self):
        log_event(0.0, "input_reader1", "start", {})
        
        # Read all lines from stdin
        lines = sys.stdin.readlines()
        requests = []
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            parts = line.split()
            if len(parts) < 3:
                continue
            
            ts_str = parts[0]
            try:
                valid = int(parts[1])
                invalid = int(parts[2])
            except ValueError:
                continue
            
            # Parse timestamp HH:MM:SS:mmm
            try:
                h, m, s, ms = map(int, ts_str.split(':'))
                ts = h * 3600 + m * 60 + s + ms / 1000.0
                requests.append((ts, valid, invalid))
            except ValueError:
                continue
        
        # Sort requests by timestamp to handle them in order
        requests.sort(key=lambda x: x[0])
        
        for ts, valid, invalid in requests:
            # Schedule a process for each request at its timestamp
            def request_handler(t, v, i):
                # Wait until the simulation time reaches the request timestamp
                yield self.env.timeout(t - self.env.now)
                
                log_event(self.env.now, "input_reader1", "input", {
                    "valid": v,
                    "invalid": i
                })
                
                # Forward to AAM
                self.env.process(self.aam.process(v, i))
            
            self.env.process(request_handler(ts, valid, invalid))

def main():
    parser = argparse.ArgumentParser(description="Internet Online Banking System Simulation")
    parser.add_argument("--simulation_time", type=float, default=1000000.0, help="Total simulation time in seconds")
    args = parser.parse_args()

    # Initialize SimPy Environment
    env = simpy.Environment()
    
    # Initialize Entities
    tpm = TPM(env)
    bpm = BPM(env, tpm)
    pv = PV(env, bpm)
    anv = ANV(env, pv)
    aam = AAM(env, anv)
    reader = InputReader(env, aam)
    
    # Start the simulation
    env.process(reader.start())
    
    # Run until the specified simulation time
    env.run(until=args.simulation_time)

if __name__ == "__main__":
    main()