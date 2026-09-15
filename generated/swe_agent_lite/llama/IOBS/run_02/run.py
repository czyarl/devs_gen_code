import argparse
import sys
import json
import logging
import random
import simpy

# Set up logging
logging.basicConfig(stream=sys.stderr)

# Define the simulation environment
env = simpy.Environment()

# Define the entities and their behaviors
class InputReader:
    def __init__(self, env):
        self.env = env

    def start(self):
        print(json.dumps({"time": self.env.now, "model": "input_reader1", "event": "start", "data": {}}))

    def read_input(self, request):
        valid, invalid = map(int, request.split())
        # Forward to AAM
        pass

# Create the input reader and start the simulation
input_reader = InputReader(env)
input_reader.start()

# Run the simulation
env.run(until=10)