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

def client_generator(env, client_mean, client_stddev, queue, client_id_gen):
    client_id = next(client_id_gen)
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
    while True:
        interval = client_mean + random.gauss(0, client_stddev)
        interval = max(0, interval)
        yield env.timeout(interval)
        client_id = next(client_id_gen)
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
    available = True
    paired_time = None
    while True:
        if available:
            try:
                client_id, arrival_time = queue.get(timeout=0)
            except simpy.Interrupt:
                continue
            paired_time = env.now
            print(json.dumps({
                "time": env.now,
                "time_str": format_time(env.now),
                "event": "client_paired",
                "entity_type": "queue",
                "entity": "Queue",
                "payload": {"client_id": client_id, "employee_id": employee_id, "paired_time": paired_time}
            }))
            available = False
            service_duration = max(mean - 3 * stddev, min(mean + 3 * stddev, mean + random.gauss(0, stddev)))
            service_duration = max(0, service_duration)
            yield env.timeout(service_duration)
            dispatched = env.now
            delay = dispatched - arrival_time
            print(json.dumps({
                "time": env.now,
                "time_str": format_time(env.now),
                "event": "client_served",
                "entity_type": "employee",
                "entity": f"Employee_{employee_id}",
                "payload": {"client_id": client_id, "employee_id": employee_id, "arrived": arrival_time, "dispatched": dispatched, "delay": delay}
            }))
            available = True
            print(json.dumps({
                "time": env.now,
                "time_str": format_time(env.now),
                "event": "employee_available",
                "entity_type": "employee",
                "entity": f"Employee_{employee_id}",
                "payload": {"employee_id": employee_id}
            }))

def main():
    args = parse_args()
    simulation_time_hours, simulation_time_minutes, simulation_time_seconds, simulation_time_milliseconds = map(int, args.simulation_time.split(':'))
    simulation_time = simulation_time_hours * 3600 + simulation_time_minutes * 60 + simulation_time_seconds + simulation_time_milliseconds / 1000

    random.seed(args.seed)

    env = simpy.Environment()
    queue = simpy.Store(env)
    client_id_gen = generate_client_id()

    env.process(client_generator(env, args.client_mean, args.client_stddev, queue, client_id_gen))
    env.process(employee(env, 1, args.employee_1_mean, args.employee_1_stddev, queue))
    env.process(employee(env, 2, args.employee_2_mean, args.employee_2_stddev, queue))

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