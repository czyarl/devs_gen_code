import argparse
import sys
import json
import logging
import simpy
import random
from collections import deque

# Set up logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

# Define constants
RECEPTION_QUEUE_CAPACITY = 8
RECEPTION_PROCESSING_TIME = 5  # seconds
HAIR_INSPECTION_TIME = 7  # seconds
HAIR_CUTTING_TIME = 20  # seconds

# Define environment
env = simpy.Environment()

# Define models
class Reception:
    def __init__(self, env, queue_capacity):
        self.env = env
        self.queue = deque(maxlen=queue_capacity)
        self.process = env.process(self.run())

    def run(self):
        while True:
            customer = yield self.env.timeout(0)
            if len(self.queue) < RECEPTION_QUEUE_CAPACITY:
                self.queue.append(customer)
                print(json.dumps({
                    "time": self.env.now,
                    "type": "state",
                    "model": "reception",
                    "field": "total customers num",
                    "value": len(self.queue)
                }))
                print(json.dumps({
                    "time": self.env.now,
                    "type": "message",
                    "model": "reception",
                    "port": "cust",
                    "content": "newcust"
                }))
            yield self.env.timeout(0)

    def check_in(self, customer):
        if len(self.queue) < RECEPTION_QUEUE_CAPACITY:
            self.queue.append(customer)
            return True
        return False

    def process_customer(self):
        if self.queue:
            customer = self.queue.popleft()
            yield self.env.timeout(RECEPTION_PROCESSING_TIME)
            return customer
        return None

class HairInspection:
    def __init__(self, env):
        self.env = env
        self.customer = None
        self.process = env.process(self.run())

    def run(self):
        while True:
            self.customer = yield self.env.timeout(0)
            yield self.env.timeout(HAIR_INSPECTION_TIME)
            print(json.dumps({
                "time": self.env.now,
                "type": "state",
                "model": "checkhair",
                "field": "customer",
                "value": "newcust"
            }))
            print(json.dumps({
                "time": self.env.now,
                "type": "message",
                "model": "checkhair",
                "port": "to_cut",
                "content": "newcust"
            }))
            yield self.env.timeout(0)

class HairCutting:
    def __init__(self, env):
        self.env = env
        self.customer = None
        self.process = env.process(self.run())

    def run(self):
        while True:
            self.customer = yield self.env.timeout(0)
            yield self.env.timeout(HAIR_CUTTING_TIME)
            print(json.dumps({
                "time": self.env.now,
                "type": "state",
                "model": "cuthair",
                "field": "total customer done",
                "value": 1
            }))
            print(json.dumps({
                "time": self.env.now,
                "type": "message",
                "model": "cuthair",
                "port": "out",
                "content": "done"
            }))
            yield self.env.timeout(0)

# Parse CLI arguments
parser = argparse.ArgumentParser()
parser.add_argument("--simulation_time", type=float, default=1000000.0)
args = parser.parse_args()

# Initialize models
reception = Reception(env, RECEPTION_QUEUE_CAPACITY)
hair_inspection = HairInspection(env)
hair_cutting = HairCutting(env)

# Read input data from stdin
customers = []
for line in sys.stdin:
    line = line.strip()
    if line:
        time, event = line.split(": ", 1)
        hours, minutes, seconds, milliseconds = map(int, time.split(":"))
        time_in_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
        customers.append((time_in_seconds, event))

# Schedule customers
for customer in customers:
    env.process(reception.check_in(customer[1]))

# Run simulation
env.run(until=args.simulation_time)

# Print final state
print(json.dumps({
    "time": env.now,
    "type": "state",
    "model": "reception",
    "field": "total customers num",
    "value": len(reception.queue)
}))