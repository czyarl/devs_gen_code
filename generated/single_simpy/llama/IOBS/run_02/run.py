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
parser.add_argument('--simulation_time', type=float, default=1000000.0)
args = parser.parse_args()

# Set seed for random number generation
random.seed(time.time_ns())

# Define simulation components
class InputReader:
    def __init__(self, env, sim_time):
        self.env = env
        self.sim_time = sim_time
        self.start_time = env.now

    def run(self):
        print(json.dumps({"time": self.env.now, "model": "input_reader1", "event": "start", "data": {}}))
        for line in sys.stdin:
            try:
                line = line.strip()
                if not line:
                    continue
                timestamp, valid, invalid = line.split()
                timestamp = time.strptime(timestamp, '%H:%M:%S:%ms')
                timestamp = (timestamp.tm_hour * 3600 + timestamp.tm_min * 60 + timestamp.tm_sec) + timestamp.tm_sec / 1000
                valid, invalid = int(valid), int(invalid)
                self.env.process(self.input_request(timestamp, valid, invalid))
            except Exception as e:
                logging.error(f"Error processing input: {e}")

    def input_request(self, timestamp, valid, invalid):
        yield self.env.timeout(timestamp - self.env.now)
        print(json.dumps({"time": self.env.now, "model": "input_reader1", "event": "input", "data": {"valid": valid, "invalid": invalid}}))
        self.env.process(self.AAM1(self.env, valid, invalid))

    def AAM1(self, env, valid, invalid):
        yield self.env.timeout(10)
        if valid == 1 and invalid == 0:
            print(json.dumps({"time": self.env.now, "model": "AAM1", "event": "account_generated", "data": {}}))
            self.env.process(self.ANV1(env))
        elif valid == 1 and invalid == 1:
            print(json.dumps({"time": self.env.now, "model": "AAM1", "event": "logout", "data": {}}))

    def ANV1(self, env):
        yield self.env.timeout(10)
        pass_verification = random.random() < 0.5
        print(json.dumps({"time": self.env.now, "model": "ANV1", "event": "verification", "data": {"pass": int(pass_verification), "fail": int(not pass_verification)}}))
        if pass_verification:
            self.env.process(self.PV1(env))

    def PV1(self, env):
        attempts = 0
        while True:
            yield self.env.timeout(10)
            attempts += 1
            if random.random() < 0.5:
                print(json.dumps({"time": self.env.now, "model": "PV1", "event": "verification", "data": {"success": 1, "attempts": attempts}}))
                self.env.process(self.BPM1(env))
                break

    def BPM1(self, env):
        yield self.env.timeout(10)
        amount = random.randint(0, 40)
        print(json.dumps({"time": self.env.now, "model": "BPM1", "event": "bill", "data": {"amount": amount}}))
        self.env.process(self.TPM1(env, amount))

    def TPM1(self, env, amount):
        balance = 3000
        yield self.env.timeout(10)
        print(json.dumps({"time": self.env.now, "model": "TPM1", "event": "transaction", "data": {"remaining": balance - amount, "count": 1}}))

def main():
    sim_time = args.simulation_time
    env = simpy.Environment()
    input_reader = InputReader(env, sim_time)
    env.process(input_reader.run())
    env.run(until=sim_time)

if __name__ == "__main__":
    main()