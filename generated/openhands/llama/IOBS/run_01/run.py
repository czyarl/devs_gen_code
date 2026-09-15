import sys
import json
import random
import time
import argparse
import logging
from collections import deque
import simpy

# Set up logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

# Parse command line arguments
parser = argparse.ArgumentParser(description='Online Banking System Simulation')
parser.add_argument('--simulation_time', type=float, default=1000000.0, help='Total simulation time in seconds')
args = parser.parse_args()

# Initialize random number generator
random.seed(time.time_ns())

# Define entities
class InputReader:
    def __init__(self, env, in_queue):
        self.env = env
        self.in_queue = in_queue

    def process(self):
        while True:
            request = sys.stdin.readline().strip().split()
            if request:
                timestamp = self.parse_timestamp(request[0])
                valid = int(request[1])
                invalid = int(request[2])
                self.in_queue.put((timestamp, valid, invalid))
                yield self.env.timeout(0)

    def parse_timestamp(self, timestamp_str):
        hours, minutes, seconds_millis = timestamp_str.split(':')
        hours, minutes, seconds, millis = int(hours), int(minutes), int(seconds_millis.split(':')[0]), int(seconds_millis.split(':')[1])
        return hours * 3600 + minutes * 60 + seconds + millis / 1000

class AAM:
    def __init__(self, env, in_queue, out_queue):
        self.env = env
        self.in_queue = in_queue
        self.out_queue = out_queue

    def process(self):
        while True:
            timestamp, valid, invalid = yield self.in_queue.get()
            if valid == 1 and invalid == 0:
                self.out_queue.put((timestamp, 'account_generated'))
            elif valid == 1 and invalid == 1:
                self.out_queue.put((timestamp, 'logout'))
            yield self.env.timeout(10)

class ANV:
    def __init__(self, env, in_queue, out_queue):
        self.env = env
        self.in_queue = in_queue
        self.out_queue = out_queue

    def process(self):
        while True:
            timestamp = yield self.in_queue.get()
            if random.random() < 0.5:
                self.out_queue.put((timestamp + 10, 'verification', {'pass': 1, 'fail': 0}))
            else:
                self.out_queue.put((timestamp + 10, 'verification', {'pass': 0, 'fail': 1}))
            yield self.env.timeout(10)

class PV:
    def __init__(self, env, in_queue, out_queue):
        self.env = env
        self.in_queue = in_queue
        self.out_queue = out_queue
        self.attempts = 0

    def process(self):
        while True:
            timestamp, _ = yield self.in_queue.get()
            self.attempts = 0
            while True:
                self.attempts += 1
                if random.random() < 0.5:
                    self.out_queue.put((timestamp + 10, 'verification', {'success': 1, 'attempts': self.attempts}))
                    break
                yield self.env.timeout(10)

class BPM:
    def __init__(self, env, in_queue, out_queue, balance):
        self.env = env
        self.in_queue = in_queue
        self.out_queue = out_queue
        self.balance = balance

    def process(self):
        while True:
            timestamp, _ = yield self.in_queue.get()
            amount = random.randint(0, 40)
            if amount > self.balance:
                amount = self.balance
            self.out_queue.put((timestamp + 10, 'bill', {'amount': amount}))
            yield self.env.timeout(10)

class TPM:
    def __init__(self, env, in_queue, out_queue, initial_balance):
        self.env = env
        self.in_queue = in_queue
        self.out_queue = out_queue
        self.balance = initial_balance
        self.transaction_count = 0

    def process(self):
        while True:
            timestamp, _, data = yield self.in_queue.get()
            self.balance -= data['amount']
            self.transaction_count += 1
            self.out_queue.put((timestamp + 10, 'transaction', {'remaining': self.balance, 'count': self.transaction_count}))
            yield self.env.timeout(10)

def main():
    env = simpy.Environment()
    in_queue = simpy.Store(env)
    aam_out_queue = simpy.Store(env)
    anv_out_queue = simpy.Store(env)
    pv_out_queue = simpy.Store(env)
    bpm_out_queue = simpy.Store(env)
    tpm_out_queue = simpy.Store(env)

    input_reader = env.process(InputReader(env, in_queue).process())
    aam = env.process(AAM(env, in_queue, aam_out_queue).process())
    anv = env.process(ANV(env, aam_out_queue, anv_out_queue).process())
    pv = env.process(PV(env, anv_out_queue, pv_out_queue).process())
    bpm = env.process(BPM(env, pv_out_queue, bpm_out_queue, 3000).process())
    tpm = env.process(TPM(env, bpm_out_queue, tpm_out_queue, 3000).process())

    while True:
        event = yield tpm_out_queue.get()
        print(json.dumps({'time': event[0], 'model': 'TPM1', 'event': 'transaction', 'data': event[2]}))

if __name__ == '__main__':
    main()
