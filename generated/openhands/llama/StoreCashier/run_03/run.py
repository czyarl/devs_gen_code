import simpy
import random
import argparse
import json
import sys

# Simulation parameters
SIMULATION_TIME = 300 # 5 minutes
CLIENT_MEAN = 10.0
CLIENT_STDDEV = 5.0
EMPLOYEE_1_MEAN = 20.0
EMPLOYEE_1_STDDEV = 0.0
EMPLOYEE_2_MEAN = 30.0
EMPLOYEE_2_STDDEV = 4.0

def generate_clients(env, client_id, client_mean, client_stddev):
    while True:
        arrival_time = env.now
        client_id += 1
        print(f"Client {client_id} arrives at {arrival_time:.2f}")
        yield env.timeout(random.gauss(client_mean, client_stddev))

def employee_service(env, employee_name, employee_mean, employee_stddev, queue):
    while True:
        client = yield queue.get()
        service_time = random.gauss(employee_mean, employee_stddev)
        print(f"{employee_name} starts serving client {client['id']} at {env.now:.2f}")
        yield env.timeout(service_time)
        print(f"{employee_name} finishes serving client {client['id']} at {env.now:.2f}")
        client['dispatched'] = env.now
        client['delay'] = client['dispatched'] - client['arrived']
        print(json.dumps({'time': env.now, 'time_str': f"{:02d}:{:02d}:{:02d}:{:03d}".format(*time_to_hms(env.now)), 'event': 'client_served', 'entity_type': 'employee', 'entity': employee_name, 'payload': {'client_id': client['id'], 'employee_id': 1 if employee_name == 'Employee_1' else 2, 'arrived': client['arrived'], 'dispatched': client['dispatched'], 'delay': client['delay']}))
        queue.task_done()

def time_to_hms(time):
    hours = int(time // 3600)
    minutes = int((time % 3600) // 60)
    seconds = int(time % 60)
    milliseconds = int((time % 1) * 1000)
    return hours, minutes, seconds, milliseconds

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulation_time', type=str, default='00:05:00:000')
    parser.add_argument('--client_mean', type=float, default=CLIENT_MEAN)
    parser.add_argument('--client_stddev', type=float, default=CLIENT_STDDEV)
    parser.add_argument('--employee_1_mean', type=float, default=EMPLOYEE_1_MEAN)
    parser.add_argument('--employee_1_stddev', type=float, default=EMPLOYEE_1_STDDEV)
    parser.add_argument('--employee_2_mean', type=float, default=EMPLOYEE_2_MEAN)
    parser.add_argument('--employee_2_stddev', type=float, default=EMPLOYEE_2_STDDEV)
    args = parser.parse_args()

    simulation_time = 300 # 5 minutes
    hours, minutes, seconds, milliseconds = args.simulation_time.split(':')
simulation_time = int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(milliseconds) / 1000

    env = simpy.Environment()
    queue = simpy.Store(env)
    client_id = 0
    client_generator = env.process(generate_clients(env, client_id, args.client_mean, args.client_stddev))
    employee_1 = env.process(employee_service(env, 'Employee_1', args.employee_1_mean, args.employee_1_stddev, queue))
    employee_2 = env.process(employee_service(env, 'Employee_2', args.employee_2_mean, args.employee_2_stddev, queue))

    print(json.dumps({'time': 0, 'time_str': "00:00:00:000", 'event': 'employee_available', 'entity_type': 'employee', 'entity': 'Employee_1', 'payload': {'employee_id': 1}}))
    print(json.dumps({'time': 0, 'time_str': "00:00:00:000", 'event': 'employee_available', 'entity_type': 'employee', 'entity': 'Employee_2', 'payload': {'employee_id': 2}}))

    try:
        env.run(until=simulation_time)
    except KeyboardInterrupt:
        pass

if __name__ == '__main__':
    main()