import argparse
import json
import random
import sys
import time
from datetime import datetime, timedelta
import simpy

def client_generator(generator, clients, client_mean, client_stddev, seed=None):
    if seed:
        random.seed(seed)
    id = 1
    while True:
        arrival_time = generator.now
        clients.put(id)
        print(json.dumps({
            'time': arrival_time,
            'time_str': datetime.fromtimestamp(arrival_time).strftime('%H:%M:%S:%f')[:-3],
            'event': 'client_generated',
            'entity_type': 'client_generator',
            'entity': 'ClientGenerator',
            'payload': {
                'client_id': id,
                'arrival_time': arrival_time
            }
        }))
        id += 1
        yield generator.timeout(client_mean + client_stddev * random.gauss(0, 1))

def employee(env, name, employee_mean, employee_stddev, clients, seed=None):
    if seed:
        random.seed(seed)
    service_time = 0
    client_id = None
    while True:
        if len(clients.queue) == 0:
            client_id = clients.get()
            print(json.dumps({
                'time': env.now,
                'time_str': datetime.fromtimestamp(env.now).strftime('%H:%M:%S:%f')[:-3],
                'event': 'client_paired',
                'entity_type': 'queue',
                'entity': 'Queue',
                'payload': {
                    'client_id': client_id,
                    'employee_id': name,
                    'paired_time': env.now
                }
            }))
            service_time = employee_mean + employee_stddev * random.gauss(0, 1)
            yield env.timeout(service_time)
            print(json.dumps({
                'time': env.now,
                'time_str': datetime.fromtimestamp(env.now).strftime('%H:%M:%S:%f')[:-3],
                'event': 'client_served',
                'entity_type': 'employee',
                'entity': name,
                'payload': {
                    'client_id': client_id,
                    'employee_id': name,
                    'arrived': env.now - service_time,
                    'dispatched': env.now,
                    'delay': service_time
                }
            }))
        else:
            print(json.dumps({
                'time': env.now,
                'time_str': datetime.fromtimestamp(env.now).strftime('%H:%M:%S:%f')[:-3],
                'event': 'employee_available',
                'entity_type': 'employee',
                'entity': name,
                'payload': {
                    'employee_id': name
                }
            }))
        yield env.timeout(0)

def run_simulation(simulation_time, client_mean, client_stddev, employee_1_mean, employee_1_stddev, employee_2_mean, employee_2_stddev, seed=None):
    env = simpy.Environment()
    clients = simpy.Store(env)
    env.process(client_generator(env, clients, client_mean, client_stddev, seed))
    env.process(employee(env, 'Employee_1', employee_1_mean, employee_1_stddev, clients, seed))
    env.process(employee(env, 'Employee_2', employee_2_mean, employee_2_stddev, clients, seed))
    env.run(until=simulation_time)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulation_time', default='00:05:00:000')
    parser.add_argument('--client_mean', type=float, default=10.0)
    parser.add_argument('--client_stddev', type=float, default=5.0)
    parser.add_argument('--employee_1_mean', type=float, default=20.0)
    parser.add_argument('--employee_1_stddev', type=float, default=0.0)
    parser.add_argument('--employee_2_mean', type=float, default=30.0)
    parser.add_argument('--employee_2_stddev', type=float, default=4.0)
    parser.add_argument('--seed', type=int)
    args = parser.parse_args()
    simulation_time = datetime.strptime(args.simulation_time, '%H:%M:%S:%f') - datetime.strptime('00:00:00:000', '%H:%M:%S:%f')
    simulation_time = simulation_time.total_seconds()
    run_simulation(simulation_time, args.client_mean, args.client_stddev, args.employee_1_mean, args.employee_1_stddev, args.employee_2_mean, args.employee_2_stddev, args.seed)