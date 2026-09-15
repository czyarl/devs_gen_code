import argparse
import sys
import json
import logging
import random
import simpy
import time
from collections import defaultdict

# Set up logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

# Parse command line arguments
parser = argparse.ArgumentParser()
parser.add_argument('--simulation_time', type=float, default=1000000.0)
args = parser.parse_args()

# Set seed for random number generation
random.seed(time.time_ns())
numpy_random = random

# Define simulation models
class InputReader:
    def __init__(self, env, name):
        self.env = env
        self.name = name
        self.start_time = 0.0

    def start(self):
        print(json.dumps({"time": self.start_time, "model": self.name, "event": "start", "data": {}}))
        for line in sys.stdin:
            try:
                line = line.strip()
                if not line:
                    continue
                timestamp, valid, invalid = line.split()
                timestamp = time.strptime(timestamp, '%H:%M:%S:%m')
                timestamp = (timestamp.tm_hour * 3600 + timestamp.tm_min * 60 + timestamp.tm_sec + timestamp.tm_sec / 1000)
                self.env.process(self.send_input(timestamp, int(valid), int(invalid)))
            except Exception as e:
                logging.error(f"Error processing input: {e}")

    def send_input(self, timestamp, valid, invalid):
        yield self.env.timeout(timestamp - self.start_time)
        print(json.dumps({"time": timestamp, "model": self.name, "event": "input", "data": {"valid": valid, "invalid": invalid}}))

class AAM:
    def __init__(self, env, name):
        self.env = env
        self.name = name

    def process(self, valid, invalid):
        if valid == 1 and invalid == 0:
            print(json.dumps({"time": self.env.now, "model": self.name, "event": "account_generated", "data": {}}))
            yield self.env.timeout(10)
            return "account_generated"
        elif valid == 1 and invalid == 1:
            print(json.dumps({"time": self.env.now, "model": self.name, "event": "logout", "data": {}}))
            yield self.env.timeout(10)
            return "logout"

class ANV:
    def __init__(self, env, name):
        self.env = env
        self.name = name

    def process(self):
        pass_or_fail = numpy_random.random()
        if pass_or_fail < 0.5:
            print(json.dumps({"time": self.env.now, "model": self.name, "event": "verification", "data": {"pass": 1, "fail": 0}}))
            yield self.env.timeout(10)
            return "pass"
        else:
            print(json.dumps({"time": self.env.now, "model": self.name, "event": "verification", "data": {"pass": 0, "fail": 1}}))
            yield self.env.timeout(10)
            return "fail"

class PV:
    def __init__(self, env, name):
        self.env = env
        self.name = name
        self.attempts = 0

    def process(self):
        while True:
            self.attempts += 1
            pass_or_fail = numpy_random.random()
            if pass_or_fail < 0.5:
                print(json.dumps({"time": self.env.now, "model": self.name, "event": "verification", "data": {"success": 1, "attempts": self.attempts}}))
                yield self.env.timeout(10)
                return

class BPM:
    def __init__(self, env, name):
        self.env = env
        self.name = name
        self.balance = 3000

    def process(self):
        amount = numpy_random.randint(0, 41)
        if amount > self.balance:
            amount = self.balance
        print(json.dumps({"time": self.env.now, "model": self.name, "event": "bill", "data": {"amount": amount}}))
        yield self.env.timeout(10)
        return amount

class TPM:
    def __init__(self, env, name):
        self.env = env
        self.name = name
        self.balance = 3000
        self.transaction_count = 0

    def process(self, amount):
        self.balance -= amount
        self.transaction_count += 1
        print(json.dumps({"time": self.env.now, "model": self.name, "event": "transaction", "data": {"remaining": self.balance, "count": self.transaction_count}}))
        yield self.env.timeout(10)

def main():
    env = simpy.Environment()
    input_reader = InputReader(env, "input_reader1")
    env.process(input_reader.start())

    aam = AAM(env, "AAM1")
    anv = ANV(env, "ANV1")
    pv = PV(env, "PV1")
    bpm = BPM(env, "BPM1")
    tpm = TPM(env, "TPM1")

    @simpy.coroutine
    def input_processed(event):
        while True:
            timestamp, valid, invalid = (yield event)
            result = yield aam.process(valid, invalid)
            if result == "account_generated":
                result = yield anv.process()
                if result == "pass":
                    yield pv.process()
                    amount = yield bpm.process()
                    yield tpm.process(amount)

    env.process(input_processed(simpy.Store()))

    try:
        env.run(until=args.simulation_time)
    except KeyboardInterrupt:
        pass

if __name__ == "__main__":
    main()