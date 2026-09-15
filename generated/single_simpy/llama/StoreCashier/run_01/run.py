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

def format_time(time):
    hours = int(time // 3600)
    minutes = int((time % 3600) // 60)
    seconds = int(time % 60)
    milliseconds = int((time % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"

def generate_client_id():
    client_id = 1
    while True:
        yield client_id
        client_id += 1

def client_generator(env, client_mean, client_stddev, queue, client_id_generator):
    client_id = next(client_id_generator)
    arrival_time = env.now
    print(json.dumps({
        "time": env.now,
        "time_str": format_time(env.now),
        "event": "client_generated",
        "entity_type": "client_generator",
        "entity": "ClientGenerator",
        "payload": {"client_id": client_id, "arrival_time": arrival_time}
    }))
    while True:
        inter_arrival_time = max(0, np.random.normal(client_mean, client_stddev))
        yield env.timeout(inter_arrival_time)
        client_id = next(client_id_generator)
        arrival_time = env.now
        print(json.dumps({
            "time": env.now,
            "time_str": format_time(env.now),
            "event": "client_generated",
            "entity_type": "client_generator",
            "entity": "ClientGenerator",
            "payload": {"client_id": client_id, "arrival_time": arrival_time}
        }))
        queue.put((client_id, arrival_time))

def employee(env, employee_id, mean, stddev, queue):
    service_time = 0
    while True:
        if not queue.empty():
            client_id, arrival_time = queue.get()
            paired_time = env.now
            print(json.dumps({
                "time": env.now,
                "time_str": format_time(env.now),
                "event": "client_paired",
                "entity_type": "queue",
                "entity": "Queue",
                "payload": {"client_id": client_id, "employee_id": employee_id, "paired_time": paired_time}
            }))
            service_time = max(0, np.random.normal(mean, stddev))
            yield env.timeout(service_time)
            dispatched_time = env.now
            delay = dispatched_time - arrival_time
            print(json.dumps({
                "time": env.now,
                "time_str": format_time(env.now),
                "event": "client_served",
                "entity_type": "employee",
                "entity": f"Employee_{employee_id}",
                "payload": {"client_id": client_id, "employee_id": employee_id, "arrived": arrival_time, "dispatched": dispatched_time, "delay": delay}
            }))
        else:
            print(json.dumps({
                "time": env.now,
                "time_str": format_time(env.now),
                "event": "employee_available",
                "entity_type": "employee",
                "entity": f"Employee_{employee_id}",
                "payload": {"employee_id": employee_id}
            }))
        yield env.timeout(0)

def main():
    args = parse_args()
    simulation_time = int(args.simulation_time.split(":")[0]) * 3600 + int(args.simulation_time.split(":")[1]) * 60 + int(args.simulation_time.split(":")[2]) + int(args.simulation_time.split(":")[3]) / 1000
    client_mean = args.client_mean
    client_stddev = args.client_stddev
    employee_1_mean = args.employee_1_mean
    employee_1_stddev = args.employee_1_stddev
    employee_2_mean = args.employee_2_mean
    employee_2_stddev = args.employee_2_stddev
    if args.seed:
        random.seed(args.seed)
        np.random.seed(args.seed)

    env = simpy.Environment()
    queue = simpy.Store(env)
    client_id_generator = generate_client_id()

    env.process(client_generator(env, client_mean, client_stddev, queue, client_id_generator))
    env.process(employee(env, 1, employee_1_mean, employee_1_stddev, queue))
    env.process(employee(env, 2, employee_2_mean, employee_2_stddev, queue))

    print(json.dumps({
        "time": 0,
        "time_str": format_time(0),
        "event": "employee_available",
        "entity_type": "employee",
        "entity": "Employee_1",
        "payload": {"employee_id": 1}
    }))
    print(json.dumps({
        "time": 0,
        "time_str": format_time(0),
        "event": "employee_available",
        "entity_type": "employee",
        "entity": "Employee_2",
        "payload": {"employee_id": 2}
    }))

    env.run(until=simulation_time)

if __name__ == "__main__":
    main()
</python_code>
```