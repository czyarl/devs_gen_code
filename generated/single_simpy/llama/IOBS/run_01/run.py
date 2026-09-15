import argparse
import sys
import json
import logging
import random
import simpy
import time
from collections import defaultdict

# Set up logging
logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

# Parse command line arguments
parser = argparse.ArgumentParser()
parser.add_argument("--simulation_time", type=float, default=1000000.0)
args = parser.parse_args()

# Set seed for random number generation
random.seed(time.time_ns())
numpy_random = random

class InputReader:
    def __init__(self, env, sim_time):
        self.env = env
        self.sim_time = sim_time
        self.start_time = env.now

    def run(self):
        print(json.dumps({"time": self.env.now, "model": "input_reader1", "event": "start", "data": {}}))

        while self.env.now < self.sim_time:
            try:
                line = sys.stdin.readline().strip()
                if line:
                    timestamp, valid, invalid = line.split()
                    valid, invalid = int(valid), int(invalid)
                    timestamp = self.parse_timestamp(timestamp)
                    if timestamp >= self.env.now:
                        self.env.process(self.input_request(timestamp, valid, invalid))
                    else:
                        logging.debug(f"Skipping request at {timestamp} as it's in the past")
                else:
                    break
            except Exception as e:
                logging.error(f"Error reading input: {e}")

    def parse_timestamp(self, timestamp):
        hours, minutes, seconds, milliseconds = map(int, timestamp.split(':'))
        return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000

    def input_request(self, timestamp, valid, invalid):
        yield self.env.timeout(timestamp - self.env.now)
        print(json.dumps({"time": self.env.now, "model": "input_reader1", "event": "input", "data": {"valid": valid, "invalid": invalid}}))
        self.env.process(AAM1(self.env, valid, invalid).run())

class AAM1:
    def __init__(self, env, valid, invalid):
        self.env = env
        self.valid = valid
        self.invalid = invalid

    def run(self):
        yield self.env.timeout(10)
        if self.valid == 1 and self.invalid == 0:
            print(json.dumps({"time": self.env.now, "model": "AAM1", "event": "account_generated", "data": {}}))
            self.env.process(ANV1(self.env).run())
        elif self.valid == 1 and self.invalid == 1:
            print(json.dumps({"time": self.env.now, "model": "AAM1", "event": "logout", "data": {}}))

class ANV1:
    def __init__(self, env):
        self.env = env

    def run(self):
        yield self.env.timeout(10)
        pass_verification = numpy_random.random() < 0.5
        if pass_verification:
            print(json.dumps({"time": self.env.now, "model": "ANV1", "event": "verification", "data": {"pass": 1, "fail": 0}}))
            self.env.process(PV1(self.env).run())
        else:
            print(json.dumps({"time": self.env.now, "model": "ANV1", "event": "verification", "data": {"pass": 0, "fail": 1}}))

class PV1:
    def __init__(self, env):
        self.env = env
        self.attempts = 0

    def run(self):
        while True:
            yield self.env.timeout(10)
            self.attempts += 1
            if numpy_random.random() < 0.5:
                print(json.dumps({"time": self.env.now, "model": "PV1", "event": "verification", "data": {"success": 1, "attempts": self.attempts}}))
                self.env.process(BPM1(self.env).run())
                break

class BPM1:
    def __init__(self, env):
        self.env = env
        self.balance = 3000

    def run(self):
        yield self.env.timeout(10)
        amount = numpy_random.randint(0, 41)
        if amount > self.balance:
            amount = self.balance
        print(json.dumps({"time": self.env.now, "model": "BPM1", "event": "bill", "data": {"amount": amount}}))
        self.env.process(TPM1(self.env, amount).run())

class TPM1:
    def __init__(self, env, amount):
        self.env = env
        self.amount = amount
        self.balance = 3000
        self.transaction_count = 0

    def run(self):
        yield self.env.timeout(10)
        self.balance -= self.amount
        self.transaction_count += 1
        print(json.dumps({"time": self.env.now, "model": "TPM1", "event": "transaction", "data": {"remaining": self.balance, "count": self.transaction_count}}))

def main():
    env = simpy.Environment()
    sim_time = args.simulation_time
    input_reader = InputReader(env, sim_time)
    env.process(input_reader.run())
    env.run(until=sim_time)

if __name__ == "__main__":
    main()