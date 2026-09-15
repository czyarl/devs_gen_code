#!/usr/bin/env python3
"""
Barbershop simulation implementation
"""
import argparse
import sys
import json
import logging
from collections import deque
import simpy

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)

class ReceptionModule:
    def __init__(self, env, checkhair_queue, capacity=8):
        self.env = env
        self.checkhair_queue = checkhair_queue
        self.capacity = capacity
        self.customers = deque()
        self.total_customers = 0
        self.processing = False
        
    def process_customer_arrival(self, customer):
        """Process customer arrival at reception"""
        # Check if queue has space
        if len(self.customers) < self.capacity:
            self.customers.append(customer)
            self.total_customers += 1
            # Log state change
            print(json.dumps({
                "time": self.env.now,
                "type": "state",
                "model": "reception",
                "field": "total customers",
                "value": self.total_customers
            }))
            
            # If not processing, start processing
            if not self.processing:
                self.env.process(self._process_queue())
        else:
            # Customer ignored, no state change
            pass
            
    def _process_queue(self):
        """Process customers in reception queue"""
        self.processing = True
        while self.customers:
            customer = self.customers.popleft()
            self.total_customers -= 1
            
            # Log message
            print(json.dumps({
                "time": self.env.now,
                "type": "message",
                "model": "reception",
                "port": "cust",
                "content": "newcust"
            }))
            
            # Process at reception (5 seconds)
            yield self.env.timeout(5.0)
            
            # Send to checkhair
            self.checkhair_queue.put(customer)
            
        self.processing = False

class CheckhairModule:
    def __init__(self, env, cuthair_queue, reception_module):
        self.env = env
        self.cuthair_queue = cuthair_queue
        self.reception_module = reception_module
        self.customer = None
        self.processing = False
        
    def process_customer(self, customer):
        """Process customer at checkhair"""
        if not self.processing:
            self.processing = True
            self.customer = customer
            
            # Log state change
            print(json.dumps({
                "time": self.env.now,
                "type": "state",
                "model": "checkhair",
                "field": "customer",
                "value": "newcust"
            }))
            
            # Process (7 seconds)
            yield self.env.timeout(7.0)
            
            # Send to cuthair
            self.cuthair_queue.put(customer)
            
            # Log message
            print(json.dumps({
                "time": self.env.now,
                "type": "message",
                "model": "checkhair",
                "port": "to_cut",
                "content": "newcust"
            }))
            
            # Wait for completion signal
            signal = yield self.cuthair_queue.get()
            
            # Log completion
            print(json.dumps({
                "time": self.env.now,
                "type": "message",
                "model": "checkhair",
                "port": "to_reception",
                "content": "done"
            }))
            
            # Log state change
            print(json.dumps({
                "time": self.env.now,
                "type": "state",
                "model": "checkhair",
                "field": "customer",
                "value": "done"
            }))
            
            self.customer = None
            self.processing = False

class CuthairModule:
    def __init__(self, env, reception_module):
        self.env = env
        self.reception_module = reception_module
        self.customers_done = 0
        self.processing = False
        
    def process_customer(self, customer):
        """Process customer at cuthair"""
        if not self.processing:
            self.processing = True
            
            # Process (20 seconds)
            yield self.env.timeout(20.0)
            
            # Signal completion
            self.customers_done += 1
            print(json.dumps({
                "time": self.env.now,
                "type": "state",
                "model": "cuthair",
                "field": "total customer done",
                "value": self.customers_done
            }))
            
            self.processing = False

def main():
    parser = argparse.ArgumentParser(description='Barbershop Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0, 
                       help='Total simulation time in seconds')
    
    args = parser.parse_args()
    
    # Read input from stdin
    events = []
    for line in sys.stdin:
        line = line.strip()
        if line:
            # Parse HH:MM:SS:mm EventName
            parts = line.split(' ', 1)
            if len(parts) == 2:
                time_str, event_name = parts
                if event_name == 'newcust':
                    # Convert time string to seconds
                    time_parts = time_str.split(':')
                    hours, minutes, seconds, milliseconds = map(int, time_parts)
                    total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
                    events.append((total_seconds, event_name))
    
    # Sort events by time
    events.sort(key=lambda x: x[0])
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create queues for communication between modules
    checkhair_queue = simpy.Store(env)
    cuthair_queue = simpy.Store(env)
    
    # Create modules
    reception = ReceptionModule(env, checkhair_queue)
    checkhair = CheckhairModule(env, cuthair_queue, reception)
    cuthair = CuthairModule(env, reception)
    
    # Schedule events at the correct times
    # The events are already sorted by time, so we can schedule them directly
    # But we need to be careful about how we schedule them
    # Since we're scheduling at the beginning of the simulation, we need to wait
    # from the current simulation time (which is 0) until the event time
    for time, event_name in events:
        # Create a generator that will wait until the event time and then process it
        def schedule_event(event_time, event_name):
            # Wait until the event time (relative to simulation start)
            # This is the key: we wait for (event_time - current_simulation_time)
            # But since we're at time 0, we wait for event_time
            yield env.timeout(event_time)
            # Process the event at the correct time
            reception.process_customer_arrival(event_name)
        
        env.process(schedule_event(time, event_name))
    
    # Run simulation
    env.run(until=args.simulation_time)
    
    # Print final state
    print(json.dumps({
        "time": args.simulation_time,
        "type": "state",
        "model": "reception",
        "field": "total customers",
        "value": reception.total_customers
    }))

if __name__ == "__main__":
    main()