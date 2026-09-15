import sys
import json
import argparse
import random
import simpy
import time
from collections import defaultdict

# Constants
SIMULATION_TIME = 1000000.0  # Default simulation time in seconds
INITIAL_BALANCE = 3000

# Command Line Arguments
parser = argparse.ArgumentParser(description='Internet Online Banking System (IOBS) Simulation')
parser.add_argument('--simulation_time', type=float, default=SIMULATION_TIME, help='Total simulation time in seconds')
args = parser.parse_args()

# Set seeds for reproducibility
random.seed(time.time_ns())

# Input Interface
def input_reader(env, queue):
    with open(0, 'r') as f:
        for line in f:
            try:
                timestamp, valid, invalid = line.strip().split()
                timestamp = float(timestamp.replace(':', '.'))
                valid = int(valid)
                invalid = int(invalid)
                yield env.timeout(timestamp)
                queue.put(('input', {'valid': valid, 'invalid': invalid}));
            except Exception as e:
                print(f"Error reading input: {e}", file=sys.stderr)

# AAM (Account Access Manager)
def aam(env, queue, anv_queue):
    while True:
        event = yield queue.get()
        if event[0] == 'input':
            data = event[1]
            if data['valid'] == 1 and data['invalid'] == 0:
                anv_queue.put(('account_generated', {}));
                print(json.dumps({'time': env.now, 'model': 'AAM1', 'event': 'account_generated', 'data': {}}), flush=True)
            elif data['valid'] == 1 and data['invalid'] == 1:
                print(json.dumps({'time': env.now, 'model': 'AAM1', 'event': 'logout', 'data': {}}), flush=True)

# ANV (Account Number Verifier)
def anv(env, queue, pv_queue):
    while True:
        event = yield queue.get()
        if event[0] == 'account_generated':
            pass_result = random.random() < 0.5
            if pass_result:
                pv_queue.put(('verification', {'pass': 1, 'fail': 0}));
                print(json.dumps({'time': env.now, 'model': 'ANV1', 'event': 'verification', 'data': {'pass': 1, 'fail': 0}}), flush=True)
            else:
                print(json.dumps({'time': env.now, 'model': 'ANV1', 'event': 'verification', 'data': {'pass': 0, 'fail': 1}}), flush=True)

# PV (Password Verifier)
def pv(env, queue, bpm_queue):
    attempts = 0
    while True:
        event = yield queue.get()
        if event[0] == 'verification':
            data = event[1]
            if data['pass'] == 1:
                attempts += 1
                success_result = random.random() < 0.5
                if success_result:
                    bpm_queue.put(('bill', {'amount': random.randint(0, 40)}));
                    print(json.dumps({'time': env.now, 'model': 'PV1', 'event': 'verification', 'data': {'success': 1, 'attempts': attempts}}), flush=True)
                else:
                    yield env.timeout(10)
                    queue.put(('verification', data));
            else:
                print(json.dumps({'time': env.now, 'model': 'PV1', 'event': 'verification', 'data': {'success': 1, 'attempts': attempts}}), flush=True)

# BPM (Bill Payment Manager)
def bpm(env, queue, tpm_queue):
    while True:
        event = yield queue.get()
        if event[0] == 'bill':
            data = event[1]
            amount = data['amount']
            tpm_queue.put(('transaction', {'amount': amount}));
            print(json.dumps({'time': env.now, 'model': 'BPM1', 'event': 'bill', 'data': {'amount': amount}}), flush=True)

# TPM (Transaction Process Manager)
def tpm(env, queue):
    balance = INITIAL_BALANCE
    transaction_count = 0
    while True:
        event = yield queue.get()
        if event[0] == 'transaction':
            data = event[1]
            amount = data['amount']
            balance -= amount
            transaction_count += 1
            print(json.dumps({'time': env.now, 'model': 'TPM1', 'event': 'transaction', 'data': {'remaining': balance, 'count': transaction_count}}), flush=True)

# Main Simulation
def main():
    env = simpy.Environment()
    queue = simpy.Store(env)
    anv_queue = simpy.Store(env)
    pv_queue = simpy.Store(env)
    bpm_queue = simpy.Store(env)
    tpm_queue = simpy.Store(env)

    env.process(input_reader(env, queue));
    env.process(aam(env, queue, anv_queue));
    env.process(anv(env, anv_queue, pv_queue));
    env.process(pv(env, pv_queue, bpm_queue));
    env.process(bpm(env, bpm_queue, tpm_queue));
    env.process(tpm(env, tpm_queue));

    print(json.dumps({'time': 0.0, 'model': 'input_reader1', 'event': 'start', 'data': {}}), flush=True)
    env.run(until=args.simulation_time)

if __name__ == '__main__':
    main()
