```python
import argparse
import json
import logging
import math
import numpy as np
import random
import simpy
import sys
import time

# Set up logging
logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

# Constants
QUEUE = "Queue"
CLIENT_GENERATOR = "ClientGenerator"
EMPLOYEE_1 = "Employee_1"
EMPLOYEE_2 = "Employee_2"

# Event types
EMPLOYEE_AVAILABLE = "employee_available"
CLIENT_GENERATED = "client_generated"
CLIENT_PAIRED = "client_paired"
CLIENT_SERVED = "client_served"

def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", default="00:05:00:000")
    parser.add_argument("--client_mean", type=float, default=10.0)
    parser.add_argument("--client_stddev", type=float, default=5.0)
    parser.add_argument("--employee_1_mean", type=float, default=20.0)
    parser.add_argument("--employee_1_stddev", type=float, default=0.0)
    parser.add_argument("--employee_2_mean", type=float, default=30.0)
    parser.add_argument("--employee_2_stddev", type=float, default=4.0)
    parser.add_argument("--seed", type=int)
    return parser.parse_args()

def format_time(time_in_seconds):
    hours = int(time_in_seconds // 3600)
    minutes = int((time_in_seconds % 3600) // 60)
    seconds = int(time_in_seconds % 60)
    milliseconds = int((time_in_seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"

class Simulation:
    def __init__(self, env, args):
        self.env = env
        self.args = args
        self.client_id = 1
        self.employee_1_available = True
        self.employee_2_available = True
        self.queue = []
        self.client_paired_times = {}

        # Set seed for reproducibility
        if args.seed:
            random.seed(args.seed)
            np.random.seed(args.seed)

        # Start client generator
        env.process(self.generate_clients())

        # Initialize employee availability
        self.emit_event(EMPLOYEE_AVAILABLE, CLIENT_GENERATOR, QUEUE, {"employee_id": 1})
        self.emit_event(EMPLOYEE_AVAILABLE, CLIENT_GENERATOR, QUEUE, {"employee_id": 2})

    def generate_clients(self):
        while True:
            arrival_time = self.env.now
            self.emit_event(CLIENT_GENERATED, CLIENT_GENERATOR, CLIENT_GENERATOR, {"client_id": self.client_id, "arrival_time": arrival_time})

            # Add client to queue
            self.queue.append(self.client_id)

            # Try to pair client with available employee
            self.try_pair_client()

            # Generate next client
            inter_arrival_time = np.random.normal(self.args.client_mean, self.args.client_stddev)
            inter_arrival_time = max(0, inter_arrival_time)
            yield self.env.timeout(inter_arrival_time)
            self.client_id += 1

    def try_pair_client(self):
        if self.queue:
            if self.employee_1_available:
                client_id = self.queue.pop(0)
                self.employee_1_available = False
                paired_time = self.env.now
                self.client_paired_times[client_id] = paired_time
                self.emit_event(CLIENT_PAIRED, QUEUE, QUEUE, {"client_id": client_id, "employee_id": 1, "paired_time": paired_time})
                self.env.process(self.serve_client(client_id, 1, self.args.employee_1_mean, self.args.employee_1_stddev))
            elif self.employee_2_available:
                client_id = self.queue.pop(0)
                self.employee_2_available = False
                paired_time = self.env.now
                self.client_paired_times[client_id] = paired_time
                self.emit_event(CLIENT_PAIRED, QUEUE, QUEUE, {"client_id": client_id, "employee_id": 2, "paired_time": paired_time})
                self.env.process(self.serve_client(client_id, 2, self.args.employee_2_mean, self.args.employee_2_stddev))

    def serve_client(self, client_id, employee_id, mean, stddev):
        service_duration = np.random.normal(mean, stddev)
        service_duration = max(0, service_duration)
        yield self.env.timeout(service_duration)
        arrived = self.env.now - service_duration
        dispatched = self.env.now
        delay = dispatched - arrived
        self.emit_event(CLIENT_SERVED, EMPLOYEE_1 if employee_id == 1 else EMPLOYEE_2, EMPLOYEE_1 if employee_id == 1 else EMPLOYEE_2, 
                         {"client_id": client_id, "employee_id": employee_id, "arrived": arrived, "dispatched": dispatched, "delay": delay})

        # Make employee available
        if employee_id == 1:
            self.employee_1_available = True
            self.emit_event(EMPLOYEE_AVAILABLE, CLIENT_GENERATOR, QUEUE, {"employee_id": 1})
        else:
            self.employee_2_available = True
            self.emit_event(EMPLOYEE_AVAILABLE, CLIENT_GENERATOR, QUEUE, {"employee_id": 2})

        # Try to pair next client
        self.try_pair_client()

    def emit_event(self, event, entity_type, entity, payload):
        time_in_seconds = self.env.now
        time_str = format_time(time_in_seconds)
        event_obj = {
            "time": time_in_seconds,
            "time_str": time_str,
            "event": event,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload
        }
        print(json.dumps(event_obj))

def main():
    args = parse_args()

    # Parse simulation time
    hours, minutes, seconds, milliseconds = map(int, args.simulation_time.split(':'))
    simulation_time_in_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000

    env = simpy.Environment()
    simulation = Simulation(env, args)
    env.run(until=simulation_time_in_seconds)

if __name__ == "__main__":
    main()
</python_code>
```