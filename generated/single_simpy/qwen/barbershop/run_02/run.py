```python
import argparse
import sys
import json
import logging
import simpy
from collections import deque
from datetime import datetime

# Global variables for simulation
simulation_time = 1000000.0
events = []

def parse_time(time_str):
    """Parse time string in format HH:MM:SS:mm to seconds"""
    h, m, s, ms = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s + ms / 100

def process_input():
    """Process all input lines to build event schedule"""
    global events
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        time_str, event_name = line.split(' ', 1)
        events.append((parse_time(time_str), event_name))

class Reception:
    def __init__(self, env, checkhair):
        self.env = env
        self.checkhair = checkhair
        self.queue = deque()
        self.total_customers = 0
        self.capacity = 8
        self.processing = False
        
    def handle_customer(self):
        while True:
            # Check if there's a customer to process
            if not self.queue:
                self.processing = False
                yield self.env.timeout(1)  # Wait for next event
                continue
                
            if self.processing:
                yield self.env.timeout(1)  # Wait for processing
                continue
                
            # Start processing the first customer in queue
            self.processing = True
            customer = self.queue[0]
            
            # Emit state change
            event = {
                "time": self.env.now,
                "type": "state",
                "model": "reception",
                "field": "total customers num",
                "value": len(self.queue)
            }
            print(json.dumps(event), file=sys.stdout)
            
            # Simulate 5 seconds processing time
            yield self.env.timeout(5)
            
            # Check if checkhair is available
            if self.checkhair.is_available():
                # Send customer to checkhair
                self.checkhair.receive_customer(customer)
                
                # Remove from queue
                self.queue.popleft()
                self.total_customers -= 1
                
                # Emit message
                event = {
                    "time": self.env.now,
                    "type": "message",
                    "model": "reception",
                    "port": "cust",
                    "content": "newcust"
                }
                print(json.dumps(event), file=sys.stdout)
                
                # Emit state change
                event = {
                    "time": self.env.now,
                    "type": "state",
                    "model": "reception",
                    "field": "total customers num",
                    "value": len(self.queue)
                }
                print(json.dumps(event), file=sys.stdout)
            else:
                # Wait until checkhair is available
                yield self.env.event()  # Placeholder for waiting logic
                
    def add_customer(self, customer):
        if len(self.queue) < self.capacity:
            self.queue.append(customer)
            self.total_customers += 1
            
            # Emit state change
            event = {
                "time": self.env.now,
                "type": "state",
                "model": "reception",
                "field": "total customers num",
                "value": len(self.queue)
            }
            print(json.dumps(event), file=sys.stdout)
            
            return True
        return False

class CheckHair:
    def __init__(self, env, cuthair):
        self.env = env
        self.cuthair = cuthair
        self.customer = None
        self.available = True
        
    def is_available(self):
        return self.available
        
    def receive_customer(self, customer):
        self.customer = customer
        self.available = False
        
        # Emit state change
        event = {
            "time": self.env.now,
            "type": "state",
            "model": "checkhair",
            "field": "customer",
            "value": "newcust"
        }
        print(json.dumps(event), file=sys.stdout)
        
        # Simulate 7 seconds processing time
        yield self.env.timeout(7)
        
        # Send customer to cuthair
        self.cuthair.receive_customer(self.customer)
        
        # Emit message
        event = {
            "time": self.env.now,
            "type": "message",
            "model": "checkhair",
            "port": "to_cut",
            "content": "newcust"
        }
        print(json.dumps(event), file=sys.stdout)
        
        # Wait for cuthair to finish
        yield self.env.event()  # Placeholder for waiting logic
        
        # Emit state change
        event = {
            "time": self.env.now,
            "type": "state",
            "model": "checkhair",
            "field": "customer",
            "value": "done"
        }
        print(json.dumps(event), file=sys.stdout)
        
        # Signal reception that service is done
        self.available = True
        self.customer = None
        
        # Emit message
        event = {
            "time": self.env.now,
            "type": "message",
            "model": "checkhair",
            "port": "to_reception",
            "content": "done"
        }
        print(json.dumps(event), file=sys.stdout)

class CutHair:
    def __init__(self, env):
        self.env = env
        self.customer = None
        self.total_done = 0
        
    def receive_customer(self, customer):
        self.customer = customer
        
        # Emit state change
        event = {
            "time": self.env.now,
            "type": "state",
            "model": "cuthair",
            "field": "total customer done",
            "value": self.total_done
        }
        print(json.dumps(event), file=sys.stdout)
        
        # Simulate 20 seconds processing time
        yield self.env.timeout(20)
        
        # Update counter
        self.total_done += 1
        
        # Emit state change
        event = {
            "time": self.env.now,
            "type": "state",
            "model": "cuthair",
            "field": "total customer done",
            "value": self.total_done
        }
        print(json.dumps(event), file=sys.stdout)
        
        # Emit message
        event = {
            "time": self.env.now,
            "type": "message",
            "model": "cuthair",
            "port": "out",
            "content": "done"
        }
        print(json.dumps(event), file=sys.stdout)
        
        self.customer = None

def run_simulation():
    # Create simulation environment
    env = simpy.Environment()
    
    # Create modules
    checkhair = CheckHair(env, None)  # Will be updated later
    cuthair = CutHair(env)
    reception = Reception(env, checkhair)
    
    # Update checkhair with cuthair reference
    checkhair.cuthair = cuthair
    
    # Start modules
    env.process(reception.handle_customer())
    
    # Process events
    for time, event_name in sorted(events):
        if event_name == "newcust":
            # Schedule customer arrival
            def customer_arrival():
                if not reception.add_customer("newcust"):
                    # Customer ignored due to full queue
                    pass
                yield env.timeout(0)  # Immediate processing
            
            env.process(customer_arrival())
    
    # Run simulation
    env.run(until=simulation_time)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulation_time', type=float, default=1000000.0)
    args = parser.parse_args()
    
    global simulation_time
    simulation_time = args.simulation_time
    
    # Process input
    process_input()
    
    # Run simulation
    run_simulation()

if __name__ == "__main__":
    main()
</python_code>
```