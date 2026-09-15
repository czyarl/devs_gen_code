```python
import argparse
import sys
import json
import logging
from collections import deque
import simpy

# Global constants
RECEPTION_QUEUE_CAPACITY = 8
RECEPTION_PROCESSING_TIME = 5.0
CHECKHAIR_PROCESSING_TIME = 7.0
CUTHAIR_PROCESSING_TIME = 20.0

# Global variables for logging
logger = logging.getLogger(__name__)

class Event:
    def __init__(self, time, event_type):
        self.time = time
        self.event_type = event_type

class Reception:
    def __init__(self, env, checkhair_queue, cuthair_queue):
        self.env = env
        self.queue = deque()
        self.checkhair_queue = checkhair_queue
        self.cuthair_queue = cuthair_queue
        self.total_customers = 0
        self.processing = False
        self.processing_event = None

    def process_customer(self):
        if self.queue:
            customer = self.queue.popleft()
            self.total_customers -= 1
            self.processing = True
            yield self.env.timeout(RECEPTION_PROCESSING_TIME)
            self.processing = False
            # Send customer to checkhair
            self.checkhair_queue.put(customer)
            # Schedule next processing
            if self.queue:
                self.env.process(self.process_customer())
        else:
            self.processing = False

    def add_customer(self, customer):
        if len(self.queue) < RECEPTION_QUEUE_CAPACITY:
            self.queue.append(customer)
            self.total_customers += 1
            # Log state change
            print(json.dumps({
                "time": self.env.now,
                "type": "state",
                "model": "reception",
                "field": "total customers num",
                "value": self.total_customers
            }), file=sys.stdout)
            
            # Start processing if not already processing
            if not self.processing:
                self.env.process(self.process_customer())
            return True
        return False

class Checkhair:
    def __init__(self, env, reception_queue, cuthair_queue):
        self.env = env
        self.reception_queue = reception_queue
        self.cuthair_queue = cuthair_queue
        self.customer = "idle"
        self.processing = False
        self.processing_event = None

    def receive_customer(self):
        if self.customer == "idle":
            customer = self.reception_queue.get()
            self.customer = "newcust"
            print(json.dumps({
                "time": self.env.now,
                "type": "state",
                "model": "checkhair",
                "field": "customer",
                "value": self.customer
            }), file=sys.stdout)
            
            # Process customer
            yield self.env.timeout(CHECKHAIR_PROCESSING_TIME)
            
            # Send to cutting phase
            self.cuthair_queue.put("newcust")
            self.customer = "done"
            print(json.dumps({
                "time": self.env.now,
                "type": "state",
                "model": "checkhair",
                "field": "customer",
                "value": self.customer
            }), file=sys.stdout)
            print(json.dumps({
                "time": self.env.now,
                "type": "message",
                "model": "checkhair",
                "port": "to_reception",
                "content": "done"
            }), file=sys.stdout)
            self.customer = "idle"
            print(json.dumps({
                "time": self.env.now,
                "type": "state",
                "model": "checkhair",
                "field": "customer",
                "value": self.customer
            }), file=sys.stdout)

    def start_processing(self):
        if self.customer == "idle":
            self.env.process(self.receive_customer())

class Cuthair:
    def __init__(self, env, checkhair_queue):
        self.env = env
        self.checkhair_queue = checkhair_queue
        self.total_customer_done = 0
        self.customer = "idle"
        self.processing = False
        self.processing_event = None

    def receive_customer(self):
        if self.customer == "idle":
            customer = self.checkhair_queue.get()
            self.customer = "newcust"
            print(json.dumps({
                "time": self.env.now,
                "type": "state",
                "model": "cuthair",
                "field": "customer",
                "value": self.customer
            }), file=sys.stdout)
            
            # Process customer
            yield self.env.timeout(CUTHAIR_PROCESSING_TIME)
            
            # Signal completion
            self.total_customer_done += 1
            self.customer = "done"
            print(json.dumps({
                "time": self.env.now,
                "type": "state",
                "model": "cuthair",
                "field": "total customer done",
                "value": self.total_customer_done
            }), file=sys.stdout)
            print(json.dumps({
                "time": self.env.now,
                "type": "message",
                "model": "cuthair",
                "port": "out",
                "content": "done"
            }), file=sys.stdout)
            self.customer = "idle"
            print(json.dumps({
                "time": self.env.now,
                "type": "state",
                "model": "cuthair",
                "field": "customer",
                "value": self.customer
            }), file=sys.stdout)

    def start_processing(self):
        if self.customer == "idle":
            self.env.process(self.receive_customer())

def parse_time(time_str):
    h, m, s, ms = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s + ms / 100.0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulation_time', type=float, default=1000000.0)
    args = parser.parse_args()
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s', stream=sys.stderr)
    
    # Read input events
    events = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        time_str, event_name = line.split(' ', 1)
        time = parse_time(time_str)
        events.append((time, event_name))
    
    # Sort events by time
    events.sort(key=lambda x: x[0])
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create queues for communication
    reception_to_checkhair = simpy.Store(env)
    checkhair_to_cuthair = simpy.Store(env)
    
    # Create modules
    reception = Reception(env, reception_to_checkhair, checkhair_to_cuthair)
    checkhair = Checkhair(env, reception_to_checkhair, checkhair_to_cuthair)
    cuthair = Cuthair(env, checkhair_to_cuthair)
    
    # Schedule events
    for time, event_name in events:
        if event_name == "newcust":
            env.process(reception.add_customer("newcust"))
    
    # Start simulation
    logger.info("Starting simulation")
    env.run(until=args.simulation_time)
    logger.info("Simulation completed")
    
    # Output final state
    print(json.dumps({
        "time": env.now,
        "type": "state",
        "model": "reception",
        "field": "total customers num",
        "value": reception.total_customers
    }), file=sys.stdout)
    
    print(json.dumps({
        "time": env.now,
        "type": "state",
        "model": "checkhair",
        "field": "customer",
        "value": checkhair.customer
    }), file=sys.stdout)
    
    print(json.dumps({
        "time": env.now,
        "type": "state",
        "model": "cuthair",
        "field": "total customer done",
        "value": cuthair.total_customer_done
    }), file=sys.stdout)

if __name__ == "__main__":
    main()
</python_code>