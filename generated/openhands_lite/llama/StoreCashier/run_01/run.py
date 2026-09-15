import argparse
import random
import json
import sys
from datetime import datetime, timedelta
import simpy

# Constants
CLIENT_GENERATOR = 'ClientGenerator'
QUEUE = 'Queue'
EMPLOYEE_1 = 'Employee_1'
EMPLOYEE_2 = 'Employee_2'

# Event types
EMPLOYEE_AVAILABLE = 'employee_available'
CLIENT_GENERATED = 'client_generated'
CLIENT_PAIRED = 'client_paired'
CLIENT_SERVED = 'client_served'

class StoreCashier:
    def __init__(self, env, client_mean, client_stddev, employee_1_mean, employee_1_stddev, employee_2_mean, employee_2_stddev):
        self.env = env
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.employee_1_mean = employee_1_mean
        self.employee_1_stddev = employee_1_stddev
        self.employee_2_mean = employee_2_mean
        self.employee_2_stddev = employee_2_stddev
        self.client_id = 0
        self.queue = []
        self.employee_1_busy = False
        self.employee_2_busy = False
        self.pairing_time = {}

        # Initial employee availability
        self.log_event(0.0, EMPLOYEE_AVAILABLE, 'employee', EMPLOYEE_1, {'employee_id': 1})
        self.log_event(0.0, EMPLOYEE_AVAILABLE, 'employee', EMPLOYEE_2, {'employee_id': 2})

        # Start client generation
        env.process(self.generate_clients())
        env.process(self.pair_clients())
        env.process(self.serve_clients())

    def generate_clients(self):
        while True:
            arrival_time = self.env.now
            self.client_id += 1
            self.log_event(arrival_time, CLIENT_GENERATED, 'client_generator', CLIENT_GENERATOR, {'client_id': self.client_id, 'arrival_time': arrival_time})
            self.queue.append(self.client_id)
            self.env.timeout(self.sample_interval())

    def pair_clients(self):
        while True:
            if self.queue and (not self.employee_1_busy or not self.employee_2_busy):
                client_id = self.queue.pop(0)
                if not self.employee_1_busy:
                    self.employee_1_busy = True
                    paired_time = self.env.now
                    self.pairing_time[client_id] = paired_time
                    self.log_event(paired_time, CLIENT_PAIRED, 'queue', QUEUE, {'client_id': client_id, 'employee_id': 1, 'paired_time': paired_time})
                else:
                    self.employee_2_busy = True
                    paired_time = self.env.now
                    self.pairing_time[client_id] = paired_time
                    self.log_event(paired_time, CLIENT_PAIRED, 'queue', QUEUE, {'client_id': client_id, 'employee_id': 2, 'paired_time': paired_time})
            self.env.timeout(0.01)

    def serve_clients(self):
        while True:
            if self.employee_1_busy:
                service_time = self.sample_service_time(EMPLOYEE_1, self.employee_1_mean, self.employee_1_stddev)
                yield self.env.timeout(service_time)
                self.log_event(self.env.now, CLIENT_SERVED, 'employee', EMPLOYEE_1, {'client_id': list(self.pairing_time.keys())[0], 'employee_id': 1, 'arrived': list(self.pairing_time.values())[0], 'dispatched': self.env.now, 'delay': self.env.now - list(self.pairing_time.values())[0]})
                self.employee_1_busy = False
                self.log_event(self.env.now, EMPLOYEE_AVAILABLE, 'employee', EMPLOYEE_1, {'employee_id': 1})
            if self.employee_2_busy:
                service_time = self.sample_service_time(EMPLOYEE_2, self.employee_2_mean, self.employee_2_stddev)
                yield self.env.timeout(service_time)
                self.log_event(self.env.now, CLIENT_SERVED, 'employee', EMPLOYEE_2, {'client_id': list(self.pairing_time.keys())[1], 'employee_id': 2, 'arrived': list(self.pairing_time.values())[1], 'dispatched': self.env.now, 'delay': self.env.now - list(self.pairing_time.values())[1]})
                self.employee_2_busy = False
                self.log_event(self.env.now, EMPLOYEE_AVAILABLE, 'employee', EMPLOYEE_2, {'employee_id': 2})
            self.env.timeout(0.01)

    def sample_interval(self):
        return random.uniform(0, self.client_mean + 5 * self.client_stddev)

    def sample_service_time(self, employee, mean, stddev):
        if stddev == 0:
            return mean
        else:
            return random.uniform(mean - 3 * stddev, mean + 3 * stddev)

    def log_event(self, time, event, entity_type, entity, payload):
        time_str = str(datetime.utcfromtimestamp(time).strftime('%H:%M:%S:%f')[:-3])
        print(json.dumps({
            'time': time,
            'time_str': time_str,
            'event': event,
            'entity_type': entity_type,
            'entity': entity,
            'payload': payload
        }))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulation_time', type=str, default='00:05:00:000')
    parser.add_argument('--client_mean', type=float, default=10.0)
    parser.add_argument('--client_stddev', type=float, default=5.0)
    parser.add_argument('--employee_1_mean', type=float, default=20.0)
    parser.add_argument('--employee_1_stddev', type=float, default=0.0)
    parser.add_argument('--employee_2_mean', type=float, default=30.0)
    parser.add_argument('--employee_2_stddev', type=float, default=4.0)
    parser.add_argument('--seed', type=int)
    args = parser.parse_args()

    hours, minutes, seconds, milliseconds = map(int, args.simulation_time.split(':'))
    simulation_time = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000

    env = simpy.Environment()
    store_cashier = StoreCashier(env, args.client_mean, args.client_stddev, args.employee_1_mean, args.employee_1_stddev, args.employee_2_mean, args.employee_2_stddev)
    env.run(until=simulation_time)

if __name__ == '__main__':
    main()