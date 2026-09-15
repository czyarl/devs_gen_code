import argparse
import sys
import json
import logging
import collections
import random
import simpy
import xdevs

import argparse
import sys
import json
import logging
from simpy import Environment

# Constants
SIMULATION_TIME = 1000000.0

# CLI Arguments
def parse_args():
    parser = argparse.ArgumentParser(description='Barbershop Simulation')
    parser.add_argument('--simulation_time', type=float, default=SIMULATION_TIME, help='Total simulation time in seconds')
    return parser.parse_args()

# Event Stream
class EventStream:
    def __init__(self):
        self.queue = []

    def add_event(self, time, event_name):
        self.queue.append((time, event_name))

    def get_events(self):
        return self.queue

# Reception Desk
class ReceptionDesk:
    def __init__(self, env, event_stream):
        self.env = env
        self.event_stream = event_stream
        self.queue = simpy.Resource(env, capacity=8)
        self.customer_count = 0

    def process_customer(self, customer):
        with self.queue.request() as req:
            yield req
            self.customer_count += 1
            print(json.dumps({'time': self.env.now, 'type': 'state', 'model': 'reception', 'field': 'total customers', 'value': self.customer_count}))
            yield self.env.timeout(5)
            print(json.dumps({'time': self.env.now, 'type': 'message', 'model': 'reception', 'port': 'cust', 'content': 'newcust'}))

# Hair Inspection Phase
class HairInspectionPhase:
    def __init__(self, env):
        self.env = env
        self.customer = None

    def process_customer(self, customer):
        self.customer = customer
        print(json.dumps({'time': self.env.now, 'type': 'state', 'model': 'checkhair', 'field': 'customer', 'value': 'newcust'}))
        yield self.env.timeout(7)
        print(json.dumps({'time': self.env.now, 'type': 'message', 'model': 'checkhair', 'port': 'to_cut', 'content': 'newcust'}))

# Hair Cutting Phase
class HairCuttingPhase:
    def __init__(self, env):
        self.env = env
        self.customer = None

    def process_customer(self, customer):
        self.customer = customer
        print(json.dumps({'time': self.env.now, 'type': 'state', 'model': 'cuthair', 'field': 'total customer done', 'value': 0}))
        yield self.env.timeout(20)
        print(json.dumps({'time': self.env.now, 'type': 'message', 'model': 'cuthair', 'port': 'out', 'content': 'done'}))

# Simulation
def simulate(env, event_stream, reception_desk, hair_inspection_phase, hair_cutting_phase):
    for time, event_name in event_stream.get_events():
        if event_name == 'newcust':
            reception_desk.process_customer('customer')

    while True:
        yield env.timeout(1)

def main():
    args = parse_args()
    event_stream = EventStream()
    for line in sys.stdin:
        line = line.strip()
        if line:
            time, event_name = line.split(': ', 1)
            event_stream.add_event(float(time), event_name)

    env = Environment()
    reception_desk = ReceptionDesk(env, event_stream)
    hair_inspection_phase = HairInspectionPhase(env)
    hair_cutting_phase = HairCuttingPhase(env)

    env.process(simulate(env, event_stream, reception_desk, hair_inspection_phase, hair_cutting_phase))
    env.run(until=args.simulation_time)

if __name__ == '__main__':
    main()
