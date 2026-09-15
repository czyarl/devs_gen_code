import argparse
import random
import json
import sys
from datetime import datetime, timedelta
import simpy

# Constants
EMPLOYEE_1_ID = 1
EMPLOYEE_2_ID = 2
CLIENT_GENERATOR_ENTITY = "ClientGenerator"
QUEUE_ENTITY = "Queue"
EMPLOYEE_1_ENTITY = "Employee_1"
EMPLOYEE_2_ENTITY = "Employee_2"

# Event types
EMPLOYEE_AVAILABLE_EVENT = "employee_available"
CLIENT_GENERATED_EVENT = "client_generated"
CLIENT_PAIRED_EVENT = "client_paired"
CLIENT_SERVED_EVENT = "client_served"

class CashierSystem:
    def __init__(self, env, client_mean, client_stddev, employee_1_mean, employee_1_stddev, employee_2_mean, employee_2_stddev):
        self.env = env
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.employee_1_mean = employee_1_mean
        self.employee_1_stddev = employee_1_stddev
        self.employee_2_mean = employee_2_mean
        self.employee_2_stddev = employee_2_stddev
        self.client_id = 0
        self.employee_1_available = True
        self.employee_2_available = True
        self.client_queue = []
        self.event_log = []

    def generate_client(self):
        self.client_id += 1
        arrival_time = self.env.now
        self.client_queue.append((self.client_id, arrival_time))
        self.log_event(CLIENT_GENERATED_EVENT, CLIENT_GENERATOR_ENTITY, {"client_id": self.client_id, "arrival_time": arrival_time})
        self.env.process(self.client_arrival(self.client_id, arrival_time))
        self.env.timer(self.client_mean + 5 * self.client_stddev).process(self.generate_client)

    def client_arrival(self, client_id, arrival_time):
        while self.employee_1_available and self.client_queue:
            client_id, arrival_time = self.client_queue.pop(0)
            self.employee_1_available = False
            self.log_event(CLIENT_PAIRED_EVENT, QUEUE_ENTITY, {"client_id": client_id, "employee_id": EMPLOYEE_1_ID, "paired_time": self.env.now})
            service_duration = self.sample_service_duration(self.employee_1_mean, self.employee_1_stddev)
            self.env.timer(service_duration).process(self.employee_1_service, client_id, arrival_time)
            break
        while self.employee_2_available and self.client_queue:
            client_id, arrival_time = self.client_queue.pop(0)
            self.employee_2_available = False
            self.log_event(CLIENT_PAIRED_EVENT, QUEUE_ENTITY, {"client_id": client_id, "employee_id": EMPLOYEE_2_ID, "paired_time": self.env.now})
            service_duration = self.sample_service_duration(self.employee_2_mean, self.employee_2_stddev)
            self.env.timer(service_duration).process(self.employee_2_service, client_id, arrival_time)
            break

    def employee_1_service(self, client_id, arrival_time):
        self.log_event(CLIENT_SERVED_EVENT, EMPLOYEE_1_ENTITY, {"client_id": client_id, "employee_id": EMPLOYEE_1_ID, "arrived": arrival_time, "dispatched": self.env.now, "delay": self.env.now - arrival_time})
        self.employee_1_available = True
        self.log_event(EMPLOYEE_AVAILABLE_EVENT, EMPLOYEE_1_ENTITY, {"employee_id": EMPLOYEE_1_ID})

    def employee_2_service(self, client_id, arrival_time):
        self.log_event(CLIENT_SERVED_EVENT, EMPLOYEE_2_ENTITY, {"client_id": client_id, "employee_id": EMPLOYEE_2_ID, "arrived": arrival_time, "dispatched": self.env.now, "delay": self.env.now - arrival_time})
        self.employee_2_available = True
        self.log_event(EMPLOYEE_AVAILABLE_EVENT, EMPLOYEE_2_ENTITY, {"employee_id": EMPLOYEE_2_ID})

    def sample_service_duration(self, mean, stddev):
        if stddev == 0:
            return mean
        else:
            return random.gauss(mean, stddev)

    def log_event(self, event, entity_type, payload):
        event_time = self.env.now
        time_str = datetime.fromtimestamp(event_time).strftime('%H:%M:%S:%f')[:-3]
        event_obj = {
            "time": event_time,
            "time_str": time_str,
            "event": event,
            "entity_type": entity_type,
            "entity": entity_type,
            "payload": payload
        }
        self.event_log.append(event_obj)
        print(json.dumps(event_obj))

    def run(self):
        self.log_event(EMPLOYEE_AVAILABLE_EVENT, EMPLOYEE_1_ENTITY, {"employee_id": EMPLOYEE_1_ID})
        self.log_event(EMPLOYEE_AVAILABLE_EVENT, EMPLOYEE_2_ENTITY, {"employee_id": EMPLOYEE_2_ID})
        self.generate_client()
        self.env.run(until=self.simulation_time)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulation_time', default="00:05:00:000")
    parser.add_argument('--client_mean', type=float, default=10.0)
    parser.add_argument('--client_stddev', type=float, default=5.0)
    parser.add_argument('--employee_1_mean', type=float, default=20.0)
    parser.add_argument('--employee_1_stddev', type=float, default=0.0)
    parser.add_argument('--employee_2_mean', type=float, default=30.0)
    parser.add_argument('--employee_2_stddev', type=float, default=4.0)
    args = parser.parse_args()

    hours, minutes, seconds, milliseconds = map(int, args.simulation_time.split(':'))
    simulation_time = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000

    env = simpy.Environment()
    cashier_system = CashierSystem(env, args.client_mean, args.client_stddev, args.employee_1_mean, args.employee_1_stddev, args.employee_2_mean, args.employee_2_stddev)
    cashier_system.simulation_time = simulation_time
    cashier_system.run()