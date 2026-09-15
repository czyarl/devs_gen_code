import sys
import json
import argparse
import random
import simpy
import logging
from collections import defaultdict

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def parse_args():
    parser = argparse.ArgumentParser(description='Internet Online Banking System (IOBS) Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0, help='Total simulation time in seconds')
    return parser.parse_args()

def input_reader(env, simulation_time, in_stream, out_stream):
    env.process(generating(env, in_stream, out_stream))

def generating(env, in_stream, out_stream):
    start_time = env.now
    for line in iter(in_stream.readline, 'EOF'):
        try:
            timestamp, valid, invalid = line.strip().split()
            timestamp = float(timestamp.replace(':', '.'))
            valid, invalid = int(valid), int(invalid)
            if valid == 1 and invalid == 0:
                env.process(AAM(env, timestamp, valid, invalid, out_stream))
            elif valid == 1 and invalid == 1:
                env.process(AAM(env, timestamp, valid, invalid, out_stream))
            else:
                logging.error('Invalid input: %s', line.strip())
        except Exception as e:
            logging.error('Error processing input: %s', e)

def AAM(env, timestamp, valid, invalid, out_stream):
    if env.now >= simulation_time:
        return
    if valid == 1 and invalid == 0:
        env.process(ANV(env, timestamp, valid, invalid, out_stream))
    elif valid == 1 and invalid == 1:
        print(json.dumps({'time': env.now, 'model': 'AAM1', 'event': 'logout', 'data': {}}), file=out_stream)

def ANV(env, timestamp, valid, invalid, out_stream):
    if env.now >= simulation_time:
        return
    # 50% chance pass, 50% chance fail
    if random.random() < 0.5:
        print(json.dumps({'time': env.now, 'model': 'ANV1', 'event': 'verification', 'data': {'pass': 1, 'fail': 0}}), file=out_stream)
        env.process(PV(env, timestamp, valid, invalid, out_stream))
    else:
        print(json.dumps({'time': env.now, 'model': 'ANV1', 'event': 'verification', 'data': {'pass': 0, 'fail': 1}}), file=out_stream)

def PV(env, timestamp, valid, invalid, out_stream):
    if env.now >= simulation_time:
        return
    attempts = 0
    while True:
        attempts += 1
        if random.random() < 0.5:
            print(json.dumps({'time': env.now, 'model': 'PV1', 'event': 'verification', 'data': {'success': 1, 'attempts': attempts}}), file=out_stream)
            env.process(BPM(env, timestamp, valid, invalid, attempts, out_stream))
            break

def BPM(env, timestamp, valid, invalid, attempts, out_stream):
    if env.now >= simulation_time:
        return
    bill_amount = random.randint(0, 40)
    print(json.dumps({'time': env.now, 'model': 'BPM1', 'event': 'bill', 'data': {'amount': bill_amount}}), file=out_stream)
    env.process(TPM(env, timestamp, valid, invalid, bill_amount, out_stream))

def TPM(env, timestamp, valid, invalid, bill_amount, out_stream):
    if env.now >= simulation_time:
        return
    balance = 3000
    remaining = balance - bill_amount
    transaction_count = 1
    print(json.dumps({'time': env.now, 'model': 'TPM1', 'event': 'transaction', 'data': {'remaining': remaining, 'count': transaction_count}}), file=out_stream)

if __name__ == '__main__':
    args = parse_args()
    simulation_time = args.simulation_time
    env = simpy.Environment()
    input_stream = sys.stdin
    output_stream = sys.stdout
    print(json.dumps({'time': 0.0, 'model': 'input_reader1', 'event': 'start', 'data': {}}), file=output_stream)
    env.process(input_reader(env, simulation_time, input_stream, output_stream))
    try:
        env.run(until=simulation_time)
    except KeyboardInterrupt:
        pass
