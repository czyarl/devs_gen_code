import argparse
import sys
import json
import logging
import random
import time
import simpy

# Configure logging to output to stderr
logging.basicConfig(
    stream=sys.stderr,
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Seed random number generator with system time
random.seed(time.time_ns())

def parse_timestamp(ts_str):
    """
    Parses a timestamp string HH:MM:SS:mmm into a float representing seconds.
    """
    parts = ts_str.split(':')
    h, m, s = map(int, parts[:3])
    ms = int(parts[3])
    return h * 3600 + m * 60 + s + ms / 1000.0

def log_event(time, model, event, data):
    """
    Prints a JSONL object to stdout.
    """
    output = {
        "time": time,
        "model": model,
        "event": event,
        "data": data
    }
    print(json.dumps(output))

class TPMModel:
    """
    TransactionProcessManager - Manages global state for transactions.
    """
    def __init__(self):
        self.balance = 3000
        self.count = 0

def run_simulation(args):
    env = simpy.Environment()
    tpm = TPMModel()

    # --- Entity Processes ---

    def tpm_process(amount):
        """
        TPM: Receives bill amount, updates balance and count.
        Delay: 10 seconds.
        """
        yield env.timeout(10)
        tpm.balance -= amount
        tpm.count += 1
        log_event(env.now, "TPM1", "transaction", {
            "remaining": tpm.balance,
            "count": tpm.count
        })

    def bpm_process():
        """
        BPM: Generates bill amount (0-40), constrained by balance.
        Delay: 10 seconds.
        """
        yield env.timeout(10)
        # Ensure amount does not exceed remaining balance
        max_amount = min(40, tpm.balance)
        amount = random.randint(0, max_amount)
        
        log_event(env.now, "BPM1", "bill", {"amount": amount})
        env.process(tpm_process(amount))

    def pv_process():
        """
        PV: Verifies password. Retries until success (50% chance per attempt).
        Delay: 10 seconds (fixed processing time).
        """
        # Logic: Try until success. 
        # Note: The prompt implies the 10s delay is the entity processing time.
        # The attempts happen logically within this window.
        attempts = 0
        while True:
            attempts += 1
            if random.random() < 0.5:
                break
        
        yield env.timeout(10)
        
        log_event(env.now, "PV1", "verification", {
            "success": 1,
            "attempts": attempts
        })
        env.process(bpm_process())

    def anv_process():
        """
        ANV: Verifies account number. 50% pass, 50% fail.
        Delay: 10 seconds.
        """
        yield env.timeout(10)
        
        passed = random.random() < 0.5
        if passed:
            log_event(env.now, "ANV1", "verification", {"pass": 1, "fail": 0})
            env.process(pv_process())
        else:
            log_event(env.now, "ANV1", "verification", {"pass": 0, "fail": 1})
            # End processing for this request (do not forward)

    def aam_process(valid, invalid):
        """
        AAM: Checks login validity.
        Delay: 10 seconds.
        """
        yield env.timeout(10)
        
        if valid == 1 and invalid == 0:
            log_event(env.now, "AAM1", "account_generated", {})
            env.process(anv_process())
        elif valid == 1 and invalid == 1:
            log_event(env.now, "AAM1", "logout", {})
            # End processing for this request

    def input_reader_process():
        """
        Reads from stdin, schedules events at correct timestamps.
        """
        log_event(env.now, "input_reader1", "start", {})
        
        # Read all lines from stdin
        lines = sys.stdin.readlines()
        
        parsed_requests = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Parse format: HH:MM:SS:mmm valid invalid
            parts = line.split()
            ts_str = parts[0]
            valid = int(parts[1])
            invalid = int(parts[2])
            
            timestamp = parse_timestamp(ts_str)
            parsed_requests.append((timestamp, valid, invalid))
        
        # Sort requests by timestamp to handle them in chronological order.
        # This ensures correct handling of close timestamps.
        parsed_requests.sort(key=lambda x: x[0])
        
        for ts, valid, invalid in parsed_requests:
            # Wait until the simulation time matches the input timestamp
            if env.now < ts:
                yield env.timeout(ts - env.now)
            
            log_event(env.now, "input_reader1", "input", {
                "valid": valid,
                "invalid": invalid
            })
            
            # Trigger AAM
            env.process(aam_process(valid, invalid))

    # Start the simulation
    env.process(input_reader_process())
    env.run(until=args.simulation_time)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Internet Online Banking System Simulation")
    parser.add_argument(
        "--simulation_time", 
        type=float, 
        default=1000000.0, 
        help="Total simulation time in seconds"
    )
    args = parser.parse_args()
    
    try:
        run_simulation(args)
    except Exception as e:
        logger.error(f"Simulation error: {e}")
        sys.exit(1)