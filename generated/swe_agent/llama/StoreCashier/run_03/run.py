import argparse
import json
import random
import sys
from datetime import datetime, timedelta
import simpy

def main():
    parser = argparse.ArgumentParser(description='Simulate a store cashier system')
    parser.add_argument('--simulation_time', default='00:05:00:000', help='total simulation horizon in HH:MM:SS:mmm format')
    parser.add_argument('--client_mean', type=float, default=10.0, help='client inter-arrival mean')
    parser.add_argument('--client_stddev', type=float, default=5.0, help='client inter-arrival stddev')
    parser.add_argument('--employee_1_mean', type=float, default=20.0, help='employee 1 service mean')
    parser.add_argument('--employee_1_stddev', type=float, default=0.0, help='employee 1 service stddev')
    parser.add_argument('--employee_2_mean', type=float, default=30.0, help='employee 2 service mean')
    parser.add_argument('--employee_2_stddev', type=float, default=4.0, help='employee 2 service stddev')
    parser.add_argument('--seed', type=int, help='seed for reproducibility')
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    # Parse simulation time
    simulation_time = timedelta(hours=int(args.simulation_time.split(':')[0]),
                                minutes=int(args.simulation_time.split(':')[1]),
                                seconds=int(args.simulation_time.split(':')[2]),
                                milliseconds=int(args.simulation_time.split(':')[3]))
    simulation_time = simulation_time.total_seconds()

    # Initialize SimPy environment
    env = simpy.Environment()

    # Client generator
    client_id = 0
    def client_generator(env, client_mean, client_stddev):
        nonlocal client_id
        arrival_time = 0.0
        while True:
            client_id += 1
            env.process(client(env, client_id, arrival_time, client_mean, client_stddev))
            arrival_time += random.gauss(client_mean, client_stddev)
            arrival_time = max(arrival_time, 0.0)
            yield env.timeout(arrival_time - (client_id - 1))

    # Client
    def client(env, client_id, arrival_time, client_mean, client_stddev):
        print(f'{env.now:.3f} Client {client_id} generated')
        # Wait for employee to be available
        with env.resource.request() as req:
            yield req
            print(f'{env.now:.3f} Client {client_id} paired with employee {req.employee_id}')
            # Simulate service
            service_time = random.gauss(employee_mean, employee_stddev)
            yield env.timeout(service_time)
            print(f'{env.now:.3f} Client {client_id} served')

    # Employee
    employee_mean = 20.0
    employee_stddev = 0.0
    class EmployeeResource(simpy.Resource):
        def __init__(self, env, capacity=1):
            super().__init__(env, capacity)
            self.employee_id = 1
        def request(self, priority=None):
            req = super().request(priority=priority)
            req.employee_id = self.employee_id
            self.employee_id = 2 if self.employee_id == 1 else 1
            return req

env.resource = EmployeeResource(env, capacity=2)

    # Run simulation
    env.process(client_generator(env, args.client_mean, args.client_stddev, env.resource))
    env.run(until=simulation_time)

if __name__ == '__main__':
    main()