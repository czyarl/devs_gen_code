import argparse
import sys
import json
import logging
import simpy
import random
import collections

# Configure logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO)

# Constants
RECEPTION_QUEUE_CAPACITY = 8
RECEPTION_PROCESSING_TIME = 5.0
HAIR_INSPECTION_TIME = 7.0
HAIR_CUTTING_TIME = 20.0

# CLI Arguments
parser = argparse.ArgumentParser(description='Barbershop Simulation')
parser.add_argument('--simulation_time', type=float, default=1000000.0)
args = parser.parse_args()

# Simulation Environment
env = simpy.Environment()

# Data Structures
reception_queue = simpy.Store(env)
hair_inspection_queue = simpy.Store(env)
hair_cutting_queue = simpy.Store(env)

# State Variables
reception_customers = 0
hair_inspection_customer = None
hair_cutting_customer = None
hair_inspection_available = True
hair_cutting_available = True

# Output Stream
def print_json(time, type, model, field=None, value=None, port=None, content=None):
    output = {
        "time": time,
        "type": type,
        "model": model
    }
    if field:
        output["field"] = field
        output["value"] = value
    if port:
        output["port"] = port
        output["content"] = content
    print(json.dumps(output))

# Reception Desk Logic
def reception_desk(env, reception_queue, hair_inspection_queue):
    global reception_customers
    while True:
        customer = yield reception_queue.get()
        if reception_customers < RECEPTION_QUEUE_CAPACITY:
            reception_customers += 1
            print_json(env.now, "state", "reception", "total customers num", reception_customers)
            print_json(env.now, "message", "reception", "cust", "newcust")
            yield env.timeout(RECEPTION_PROCESSING_TIME)
            if hair_inspection_available:
                hair_inspection_available = False
                hair_inspection_customer = customer
                hair_inspection_queue.put(customer)
                reception_customers -= 1
                print_json(env.now, "state", "reception", "total customers num", reception_customers)
                print_json(env.now, "message", "reception", "cust", "newcust")
            else:
                yield env.timeout(0.1)  # wait and try again

# Hair Inspection Phase Logic
def hair_inspection_phase(env, hair_inspection_queue, hair_cutting_queue):
    global hair_inspection_available, hair_inspection_customer
    while True:
        customer = yield hair_inspection_queue.get()
        hair_inspection_available = False
        print_json(env.now, "state", "checkhair", "customer", "newcust")
        yield env.timeout(HAIR_INSPECTION_TIME)
        hair_cutting_queue.put(customer)
        print_json(env.now, "message", "checkhair", "to_cut", "newcust")
        hair_inspection_customer = None
        hair_inspection_available = True
        print_json(env.now, "state", "checkhair", "customer", "done")
        print_json(env.now, "message", "checkhair", "to_reception", "done")

# Hair Cutting Phase Logic
def hair_cutting_phase(env, hair_cutting_queue, hair_inspection_queue):
    global hair_cutting_available, hair_cutting_customer
    while True:
        customer = yield hair_cutting_queue.get()
        hair_cutting_available = False
        print_json(env.now, "state", "cuthair", "total customer done", 0)
        yield env.timeout(HAIR_CUTTING_TIME)
        hair_cutting_customer = None
        hair_cutting_available = True
        print_json(env.now, "message", "cuthair", "out", "done")
        print_json(env.now, "state", "cuthair", "total customer done", 1)

# Read Input from stdin
def read_input(env, reception_queue):
    for line in sys.stdin:
        line = line.strip()
        if line:
            time_str, event = line.split(": ", 1)
            hours, minutes, seconds, _ = map(int, time_str.split(":"))
            time = hours * 3600 + minutes * 60 + seconds
            if event == "newcust":
                reception_queue.put(event)

# Run Simulation
def run_simulation():
    reception_process = env.process(reception_desk(env, reception_queue, hair_inspection_queue))
    hair_inspection_process = env.process(hair_inspection_phase(env, hair_inspection_queue, hair_cutting_queue))
    hair_cutting_process = env.process(hair_cutting_phase(env, hair_cutting_queue, hair_inspection_queue))
    read_input(env, reception_queue)
    try:
        env.run(until=args.simulation_time)
    except Exception as e:
        logging.error(f"Simulation failed: {e}")

if __name__ == "__main__":
    run_simulation()