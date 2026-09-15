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

# Configure logging
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
    seconds_parts = parts[2].split('.')
    seconds = int(seconds_parts[0])
    milliseconds = int(seconds_parts[1]) if len(seconds_parts) > 1 else 0
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


def input_reader_process(env, aam_queue, input_lines):
    """Input reader process that reads requests and forwards to AAM"""
    # Output start event at t=0
    output_event(env.now, "input_reader1", "start", {})
    
    for line in input_lines:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split()
        if len(parts) < 3:
            continue
        
        timestamp_str = parts[0]
        valid = int(parts[1])
        invalid = int(parts[2])
        
        # Wait until the input timestamp
        target_time = parse_timestamp(timestamp_str)
        if env.now < target_time:
            yield env.timeout(target_time - env.now)
        
        # Output input event
        output_event(env.now, "input_reader1", "input", {"valid": valid, "invalid": invalid})
        
        # Forward to AAM
        aam_queue.put({
            'valid': valid,
            'invalid': invalid,
            'arrival_time': env.now
        })
    
    logger.info("Input reader finished processing all requests")


def aam_process(env, aam_queue, anv_queue):
    """Account Access Manager process"""
    while True:
        # Wait for request from input reader
        request = yield aam_queue.get()
        
        # Processing delay of 10 seconds
        yield env.timeout(10)
        
        valid = request['valid']
        invalid = request['invalid']
        
        if valid == 1 and invalid == 0:
            # Valid login - forward to ANV
            output_event(env.now, "AAM1", "account_generated", {})
            anv_queue.put(request)
        elif valid == 1 and invalid == 1:
            # Invalid login - trigger logout
            output_event(env.now, "AAM1", "logout", {})


def anv_process(env, anv_queue, pv_queue):
    """Account Number Verifier process"""
    while True:
        # Wait for request from AAM
        request = yield anv_queue.get()
        
        # Processing delay of 10 seconds
        yield env.timeout(10)
        
        # Random verification: 50% pass, 50% fail
        if random.random() < 0.5:
            # Pass - forward to PV
            output_event(env.now, "ANV1", "verification", {"pass": 1, "fail": 0})
            pv_queue.put(request)
        else:
            # Fail - end processing
            output_event(env.now, "ANV1", "verification", {"pass": 0, "fail": 1})


def pv_process(env, pv_queue, bpm_queue):
    """Password Verifier process"""
    while True:
        # Wait for request from ANV
        request = yield pv_queue.get()
        
        attempts = 0
        while True:
            attempts += 1
            # Processing delay of 10 seconds per attempt
            yield env.timeout(10)
            
            # Random password check: 50% chance success per attempt
            if random.random() < 0.5:
                # Success - forward to BPM
                output_event(env.now, "PV1", "verification", {"success": 1, "attempts": attempts})
                bpm_queue.put(request)
                break


def bpm_process(env, bpm_queue, tpm_queue, remaining_balance):
    """Bill Payment Manager process"""
    while True:
        # Wait for request from PV
        request = yield bpm_queue.get()
        
        # Processing delay of 10 seconds
        yield env.timeout(10)
        
        # Generate random bill amount between 0 and 40
        # Make sure it does not exceed remaining balance
        max_amount = min(40, remaining_balance['value'])
        amount = random.randint(0, max_amount)
        
        # Output bill event
        output_event(env.now, "BPM1", "bill", {"amount": amount})
        
        # Forward to TPM
        tpm_queue.put({
            'amount': amount,
            'arrival_time': env.now
        })


def tpm_process(env, tpm_queue, balance, transaction_count):
    """Transaction Process Manager process"""
    while True:
        # Wait for request from BPM
        request = yield tpm_queue.get()
        
        # Processing delay of 10 seconds
        yield env.timeout(10)
        
        amount = request['amount']
        
        # Calculate remaining balance
        balance['value'] -= amount
        transaction_count['value'] += 1
        
        # Output transaction event
        output_event(env.now, "TPM1", "transaction", {
            "remaining": balance['value'],
            "count": transaction_count['value']
        })


def main():
    """Main simulation function"""
    parser = argparse.ArgumentParser(description='Internet Online Banking System Simulation')
    parser.add_argument(
        '--simulation_time',
        type=float,
        default=1000000.0,
        help='Total simulation time in seconds'
    )
    args = parser.parse_args()
    
    logger.info(f"Starting IOBS simulation with simulation_time={args.simulation_time}")
    
    # Read all input lines from stdin
    input_lines = []
    for line in sys.stdin:
        input_lines.append(line)
    
    logger.info(f"Read {len(input_lines)} input lines")
    
    # Create simpy environment
    env = simpy.Environment()
    
    # Create queues for communication between components
    aam_queue = simpy.Store(env)
    anv_queue = simpy.Store(env)
    pv_queue = simpy.Store(env)
    bpm_queue = simpy.Store(env)
    tpm_queue = simpy.Store(env)
    
    # Shared state
    balance = {'value': 3000}
    transaction_count = {'value': 0}
    
    # Start all processes
    env.process(input_reader_process(env, aam_queue, input_lines))
    env.process(aam_process(env, aam_queue, anv_queue))
    env.process(anv_process(env, anv_queue, pv_queue))
    env.process(pv_process(env, pv_queue, bpm_queue))
    env.process(bpm_process(env, bpm_queue, tpm_queue, balance))
    env.process(tpm_process(env, tpm_queue, balance, transaction_count))
    
    # Run simulation
    env.run(until=args.simulation_time)
    
    logger.info(f"Simulation completed at time {env.now}")
    logger.info(f"Final balance: {balance['value']}, Total transactions: {transaction_count['value']}")


if __name__ == '__main__':
    main()