import argparse
import sys
import json
import logging
import collections
import random
import simpy
import xdevs

# Configure logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

# Define constants
RECEPTION_QUEUE_CAPACITY = 8

# Define the simulation environment
class BarberShopSimulation:
    def __init__(self, env, simulation_time):
        self.env = env
        self.simulation_time = simulation_time
        self.reception_queue = simpy.Store(env)
        self.reception_customer_count = 0
        self.checkhair_customer = None
        self.cuthair_customer = None
        self.checkhair_available = True
        self.cuthair_available = True

    def reception_desk(self):
        while True:
            customer = yield self.reception_queue.get()
            if self.reception_customer_count < RECEPTION_QUEUE_CAPACITY:
                self.reception_customer_count += 1
                print(json.dumps({
                    "time": self.env.now,
                    "type": "state",
                    "model": "reception",
                    "field": "total customers",
                    "value": self.reception_customer_count
                }))
                print(json.dumps({
                    "time": self.env.now,
                    "type": "message",
                    "model": "reception",
                    "port": "cust",
                    "content": "newcust"
                }))
                yield self.env.timeout(5)
                self.reception_customer_count -= 1
                if self.checkhair_available:
                    self.checkhair_available = False
                    self.checkhair_customer = customer
                    print(json.dumps({
                        "time": self.env.now,
                        "type": "message",
                        "model": "reception",
                        "port": "cust",
                        "content": "newcust"
                    }))

    def hair_inspection_phase(self):
        while True:
            if self.checkhair_customer:
                yield self.env.timeout(7)
                print(json.dumps({
                    "time": self.env.now,
                    "type": "state",
                    "model": "checkhair",
                    "field": "customer",
                    "value": "newcust"
                }))
                self.cuthair_customer = self.checkhair_customer
                self.checkhair_customer = None
                self.checkhair_available = False
                print(json.dumps({
                    "time": self.env.now,
                    "type": "message",
                    "model": "checkhair",
                    "port": "to_cut",
                    "content": "newcust"
                }))
            else:
                yield self.env.timeout(0.1)

    def hair_cutting_phase(self):
        while True:
            if self.cuthair_customer:
                yield self.env.timeout(20)
                print(json.dumps({
                    "time": self.env.now,
                    "type": "state",
                    "model": "cuthair",
                    "field": "total customer done",
                    "value": 1
                }))
                print(json.dumps({
                    "time": self.env.now,
                    "type": "message",
                    "model": "cuthair",
                    "port": "out",
                    "content": "done"
                }))
                self.cuthair_available = True
                self.checkhair_available = True
                print(json.dumps({
                    "time": self.env.now,
                    "type": "message",
                    "model": "checkhair",
                    "port": "to_reception",
                    "content": "done"
                }))
                self.cuthair_customer = None
            else:
                yield self.env.timeout(0.1)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=float, default=1000000.0)
    args = parser.parse_args()

    env = simpy.Environment()
    simulation = BarberShopSimulation(env, args.simulation_time)

    reception_process = env.process(simulation.reception_desk())
    checkhair_process = env.process(simulation.hair_inspection_phase())
    cuthair_process = env.process(simulation.hair_cutting_phase())

    for line in sys.stdin:
        line = line.strip()
        if line:
            time, event = line.split(": ", 1)
            hours, minutes, seconds, milliseconds = map(int, time.split(":"))
            time_in_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
            if event == "newcust":
                env.process(simulation.reception_queue.put("newcust"))

    env.run(until=args.simulation_time)

if __name__ == "__main__":
    main()