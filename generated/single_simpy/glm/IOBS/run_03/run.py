import argparse
import sys
import json
import logging
import random
import time
import simpy

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)
logger = logging.getLogger(__name__)

# Set random seed using system time
random.seed(time.time_ns())


def parse_timestamp(ts_str):
    """Parse timestamp string HH:MM:SS:mmm to seconds"""
    parts = ts_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def output_event(time, model, event, data):
    """Output event as JSONL to stdout"""
    event_obj = {
        "time": time,
        "model": model,
        "event": event,
        "data": data
    }
    print(json.dumps(event_obj))


class InputReader:
    def __init__(self, env, aam):
        self.env = env
        self.aam = aam
        self.requests = []
        
    def load_requests(self):
        """Read all requests from stdin"""
        for line in sys.stdin:
            line = line.strip()
            if line:
                parts = line.split()
                ts_str = parts[0]
                valid = int(parts[1])
                invalid = int(parts[2])
                timestamp = parse_timestamp(ts_str)
                self.requests.append((timestamp, valid, invalid))
        
        # Sort by timestamp
        self.requests.sort(key=lambda x: x[0])
        
    def run(self):
        """Main process for input reader"""
        output_event(0.0, "input_reader1", "start", {})
        
        for timestamp, valid, invalid in self.requests:
            # Wait until the request timestamp
            yield self.env.timeout(timestamp - self.env.now)
            
            # Output input event
            output_event(self.env.now, "input_reader1", "input", {"valid": valid, "invalid": invalid})
            
            # Forward to AAM immediately
            self.aam.process_request(valid, invalid)


class AAM:
    def __init__(self, env, anv):
        self.env = env
        self.anv = anv
        
    def process_request(self, valid, invalid):
        """Process login request"""
        def _process():
            # 10s processing delay
            yield self.env.timeout(10)
            
            if valid == 1 and invalid == 0:
                output_event(self.env.now, "AAM1", "account_generated", {})
                self.anv.verify_account()
            elif valid == 1 and invalid == 1:
                output_event(self.env.now, "AAM1", "logout", {})
        
        self.env.process(_process())


class ANV:
    def __init__(self, env, pv):
        self.env = env
        self.pv = pv
        
    def verify_account(self):
        """Verify account number"""
        def _verify():
            # 10s processing delay
            yield self.env.timeout(10)
            
            # 50% chance pass, 50% chance fail
            pass_result = 1 if random.random() < 0.5 else 0
            fail_result = 0 if pass_result == 1 else 1
            
            output_event(self.env.now, "ANV1", "verification", {"pass": pass_result, "fail": fail_result})
            
            if pass_result == 1:
                self.pv.verify_password()
        
        self.env.process(_verify())


class PV:
    def __init__(self, env, bpm):
        self.env = env
        self.bpm = bpm
        
    def verify_password(self):
        """Verify password - keeps trying until success"""
        def _verify():
            # 10s processing delay
            yield self.env.timeout(10)
            
            # Simulate attempts until success (50% chance per attempt)
            attempts = 0
            while True:
                attempts += 1
                if random.random() < 0.5:  # Success
                    break
            
            output_event(self.env.now, "PV1", "verification", {"success": 1, "attempts": attempts})
            self.bpm.generate_bill()
        
        self.env.process(_verify())


class BPM:
    def __init__(self, env, tpm):
        self.env = env
        self.tpm = tpm
        
    def generate_bill(self):
        """Generate bill amount"""
        def _generate():
            # 10s processing delay
            yield self.env.timeout(10)
            
            # Generate random amount between 0 and 40
            amount = random.randint(0, 40)
            
            output_event(self.env.now, "BPM1", "bill", {"amount": amount})
            
            self.tpm.process_transaction(amount)
        
        self.env.process(_generate())


class TPM:
    def __init__(self, env):
        self.env = env
        self.balance = 3000
        self.count = 0
        
    def process_transaction(self, amount):
        """Process transaction"""
        def _process():
            # 10s processing delay
            yield self.env.timeout(10)
            
            # Make sure amount doesn't exceed remaining balance
            if amount > self.balance:
                amount = self.balance
            
            self.balance -= amount
            self.count += 1
            
            output_event(self.env.now, "TPM1", "transaction", {"remaining": self.balance, "count": self.count})
        
        self.env.process(_process())


def main():
    parser = argparse.ArgumentParser(description='Internet Online Banking System Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0,
                        help='Total simulation time in seconds')
    args = parser.parse_args()
    
    # Create SimPy environment
    env = simpy.Environment()
    
    # Create components
    tpm = TPM(env)
    bpm = BPM(env, tpm)
    pv = PV(env, bpm)
    anv = ANV(env, pv)
    aam = AAM(env, anv)
    input_reader = InputReader(env, aam)
    
    # Load requests from stdin
    input_reader.load_requests()
    
    # Start simulation
    env.process(input_reader.run())
    
    # Run simulation
    env.run(until=args.simulation_time)
    
    logger.info(f"Simulation completed. Final time: {env.now}")


if __name__ == "__main__":
    main()