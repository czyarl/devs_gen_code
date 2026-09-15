#!/usr/bin/env python3
"""
Internet Online Banking System (IOBS) - Discrete Event Simulation
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

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


def parse_timestamp(timestamp_str):
    """Parse timestamp string HH:MM:SS:mmm to seconds"""
    parts = timestamp_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3]) if len(parts) > 3 else 0
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def output_event(time, model, event, data):
    """Output event to stdout as JSONL"""
    event_obj = {
        "time": time,
        "model": model,
        "event": event,
        "data": data
    }
    print(json.dumps(event_obj))


def input_reader_process(env, aam_queue, requests):
    """Input reader process that reads requests and forwards to AAM"""
    output_event(env.now, "input_reader1", "start", {})
    
    for request in requests:
        # Wait until the request timestamp
        if env.now < request['timestamp']:
            yield env.timeout(request['timestamp'] - env.now)
        
        # Process the input with 10s delay
        output_event(env.now, "input_reader1", "input", {
            "valid": request['valid'],
            "invalid": request['invalid']
        })
        
        yield env.timeout(10)
        
        # Forward to AAM
        yield aam_queue.put(request)


def aam_process(env, aam_queue, anv_queue):
    """Account Access Manager process"""
    while True:
        request = yield aam_queue.get()
        
        # Process with 10s delay
        yield env.timeout(10)
        
        if request['valid'] == 1 and request['invalid'] == 0:
            # Valid login - forward to ANV
            output_event(env.now, "AAM1", "account_generated", {})
            yield anv_queue.put(request)
        elif request['valid'] == 1 and request['invalid'] == 1:
            # Invalid login - logout
            output_event(env.now, "AAM1", "logout", {})


def anv_process(env, anv_queue, pv_queue):
    """Account Number Verifier process"""
    while True:
        request = yield anv_queue.get()
        
        # Process with 10s delay
        yield env.timeout(10)
        
        # 50% chance pass, 50% chance fail
        if random.random() < 0.5:
            # Pass - forward to PV
            output_event(env.now, "ANV1", "verification", {"pass": 1, "fail": 0})
            yield pv_queue.put(request)
        else:
            # Fail - end processing
            output_event(env.now, "ANV1", "verification", {"pass": 0, "fail": 1})


def pv_process(env, pv_queue, bpm_queue):
    """Password Verifier process"""
    while True:
        request = yield pv_queue.get()
        
        attempts = 0
        success = False
        
        # Keep trying until success (50% chance per attempt)
        while not success:
            attempts += 1
            if random.random() < 0.5:
                success = True
        
        # Process with 10s delay
        yield env.timeout(10)
        
        output_event(env.now, "PV1", "verification", {
            "success": 1,
            "attempts": attempts
        })
        
        # Forward to BPM
        yield bpm_queue.put(request)


def bpm_process(env, bpm_queue, tpm_queue, remaining_balance):
    """Bill Payment Manager process"""
    while True:
        request = yield bpm_queue.get()
        
        # Process with 10s delay
        yield env.timeout(10)
        
        # Generate random bill amount between 0 and 40
        # Make sure it doesn't exceed remaining balance
        max_amount = min(40, remaining_balance['value'])
        amount = random.randint(0, max_amount)
        
        output_event(env.now, "BPM1", "bill", {"amount": amount})
        
        # Forward to TPM
        yield tpm_queue.put({"amount": amount})


def tpm_process(env, tpm_queue, remaining_balance, transaction_count):
    """Transaction Process Manager process"""
    while True:
        data = yield tpm_queue.get()
        
        # Process with 10s delay
        yield env.timeout(10)
        
        # Calculate remaining balance
        remaining_balance['value'] -= data['amount']
        transaction_count['value'] += 1
        
        output_event(env.now, "TPM1", "transaction", {
            "remaining": remaining_balance['value'],
            "count": transaction_count['value']
        })


def main():
    parser = argparse.ArgumentParser(description='IOBS Discrete Event Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0,
                        help='Total simulation time in seconds')
    args = parser.parse_args()
    
    logger.info(f"Starting IOBS simulation with max time: {args.simulation_time}s")
    
    # Read input from stdin
    requests = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split()
        if len(parts) >= 3:
            timestamp = parse_timestamp(parts[0])
            valid = int(parts[1])
            invalid = int(parts[2])
            requests.append({
                'timestamp': timestamp,
                'valid': valid,
                'invalid': invalid
            })
    
    logger.info(f"Read {len(requests)} requests from stdin")
    
    # Create simpy environment
    env = simpy.Environment()
    
    # Create queues for communication between entities
    aam_queue = simpy.Store(env)
    anv_queue = simpy.Store(env)
    pv_queue = simpy.Store(env)
    bpm_queue = simpy.Store(env)
    tpm_queue = simpy.Store(env)
    
    # Shared state
    remaining_balance = {'value': 3000}
    transaction_count = {'value': 0}
    
    # Start all processes
    env.process(input_reader_process(env, aam_queue, requests))
    env.process(aam_process(env, aam_queue, anv_queue))
    env.process(anv_process(env, anv_queue, pv_queue))
    env.process(pv_process(env, pv_queue, bpm_queue))
    env.process(bpm_process(env, bpm_queue, tpm_queue, remaining_balance))
    env.process(tpm_process(env, tpm_queue, remaining_balance, transaction_count))
    
    # Run simulation
    logger.info("Running simulation...")
    env.run(until=args.simulation_time)
    
    logger.info(f"Simulation completed. Final balance: {remaining_balance['value']}, "
                f"Total transactions: {transaction_count['value']}")


if __name__ == '__main__':
    main()
