#!/usr/bin/env python3
"""
Barbershop Simulation using Discrete Event Simulation (DES) with SimPy
"""

import argparse
import sys
import json
import logging
from collections import deque
import simpy


# Configure logging to stderr
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format='%(message)s')


class ReceptionDesk:
    """Reception desk module for barbershop simulation"""
    
    def __init__(self, env, checkhair_queue, simulation_time):
        self.env = env
        self.checkhair_queue = checkhair_queue
        self.simulation_time = simulation_time
        self.queue = deque()  # Queue of waiting customers
        self.total_customers = 0  # Total customers processed
        self.waiting_area_capacity = 8
        self.processing_time = 5.0  # seconds
        
        # Start monitoring for customers
        self.env.process(self.monitor_queue())
        
    def monitor_queue(self):
        """Monitor the queue and process customers"""
        while True:
            # Check if there are customers in the queue
            if self.queue:
                # Process the first customer in queue
                customer_id = self.queue[0]
                # Process the customer (5 seconds)
                yield self.env.timeout(self.processing_time)
                
                # Send customer to checkhair
                self.checkhair_queue.put(customer_id)
                logging.debug(f"Reception: Customer {customer_id} sent to checkhair")
                
                # Emit message event
                event_data = {
                    "time": self.env.now,
                    "type": "message",
                    "model": "reception",
                    "port": "cust",
                    "content": "newcust"
                }
                print(json.dumps(event_data))
                
                # Remove customer from queue
                self.queue.popleft()
                
                # Emit state change for queue size
                event_data = {
                    "time": self.env.now,
                    "type": "state",
                    "model": "reception",
                    "field": "queue size",
                    "value": len(self.queue)
                }
                print(json.dumps(event_data))
            else:
                # Wait for a bit before checking again
                yield self.env.timeout(0.1)
    
    def add_customer(self, customer_id):
        """Add a customer to the reception queue"""
        # Check if we can accept the customer
        if len(self.queue) < self.waiting_area_capacity:
            self.queue.append(customer_id)
            self.total_customers += 1
            
            # Emit state change for total customers
            event_data = {
                "time": self.env.now,
                "type": "state",
                "model": "reception",
                "field": "total customers num",
                "value": self.total_customers
            }
            print(json.dumps(event_data))
            
            # Emit state change for queue size
            event_data = {
                "time": self.env.now,
                "type": "state",
                "model": "reception",
                "field": "queue size",
                "value": len(self.queue)
            }
            print(json.dumps(event_data))
            
            return True
        else:
            # Customer rejected due to full queue
            logging.debug(f"Reception: Customer {customer_id} rejected - queue full")
            # No state change needed, just ignore the customer
            return False


class CheckHair:
    """Hair inspection phase module for barbershop simulation"""
    
    def __init__(self, env, cuthair_queue, checkhair_queue, simulation_time):
        self.env = env
        self.cuthair_queue = cuthair_queue
        self.checkhair_queue = checkhair_queue
        self.simulation_time = simulation_time
        self.customer = None  # Current customer being inspected
        self.processing_time = 7.0  # seconds
        self.available = True  # Whether the module is available
        
        # Start monitoring for customers
        self.env.process(self.monitor_queue())
        
    def monitor_queue(self):
        """Monitor the queue and process customers"""
        while True:
            # Check if there are customers in the queue
            if not self.available:
                # Module is busy, wait
                yield self.env.timeout(0.1)
                continue
                
            # Try to get a customer from the queue
            try:
                customer_id = self.checkhair_queue.get_nowait()
                # Process the customer
                yield self.env.process(self.process_customer(customer_id))
            except simpy.Empty:
                # No customer in queue, wait a bit
                yield self.env.timeout(0.1)
    
    def process_customer(self, customer_id):
        """Process a customer at the hair inspection phase"""
        self.available = False
        self.customer = customer_id
        logging.debug(f"CheckHair: Processing customer {customer_id}")
        
        # Emit state change for customer status
        event_data = {
            "time": self.env.now,
            "type": "state",
            "model": "checkhair",
            "field": "customer",
            "value": "newcust"
        }
        print(json.dumps(event_data))
        
        # Process the customer (7 seconds)
        yield self.env.timeout(self.processing_time)
        
        # Send customer to cutting phase
        self.cuthair_queue.put(customer_id)
        logging.debug(f"CheckHair: Customer {customer_id} sent to cuthair")
        
        # Emit message event
        event_data = {
            "time": self.env.now,
            "type": "message",
            "model": "checkhair",
            "port": "to_cut",
            "content": "newcust"
        }
        print(json.dumps(event_data))
        
        # Mark as available again
        self.customer = None
        self.available = True
        
        # Emit state change for customer status
        event_data = {
            "time": self.env.now,
            "type": "state",
            "model": "checkhair",
            "field": "customer",
            "value": "done"
        }
        print(json.dumps(event_data))
        
        # Notify reception that service is complete
        # For now, we'll just emit a message
        event_data = {
            "time": self.env.now,
            "type": "message",
            "model": "checkhair",
            "port": "to_reception",
            "content": "done"
        }
        print(json.dumps(event_data))


class CutHair:
    """Hair cutting phase module for barbershop simulation"""
    
    def __init__(self, env, checkhair_queue, simulation_time):
        self.env = env
        self.checkhair_queue = checkhair_queue
        self.simulation_time = simulation_time
        self.total_customer_done = 0  # Counter for completed customers
        self.processing_time = 20.0  # seconds
        self.customer = None  # Current customer being cut
        
        # Start monitoring for customers
        self.env.process(self.monitor_queue())
        
    def monitor_queue(self):
        """Monitor the queue and process customers"""
        while True:
            # Try to get a customer from the queue
            try:
                customer_id = self.checkhair_queue.get_nowait()
                # Process the customer
                yield self.env.process(self.process_customer(customer_id))
            except simpy.Empty:
                # No customer in queue, wait a bit
                yield self.env.timeout(0.1)
    
    def process_customer(self, customer_id):
        """Process a customer at the hair cutting phase"""
        self.customer = customer_id
        logging.debug(f"CutHair: Processing customer {customer_id}")
        
        # Emit state change for customer status
        event_data = {
            "time": self.env.now,
            "type": "state",
            "model": "cuthair",
            "field": "customer",
            "value": "newcust"
        }
        print(json.dumps(event_data))
        
        # Process the customer (20 seconds)
        yield self.env.timeout(self.processing_time)
        
        # Signal completion back to checkhair
        self.total_customer_done += 1
        self.customer = None
        
        # Emit state change for completed customers
        event_data = {
            "time": self.env.now,
            "type": "state",
            "model": "cuthair",
            "field": "total customer done",
            "value": self.total_customer_done
        }
        print(json.dumps(event_data))
        
        # Emit message event
        event_data = {
            "time": self.env.now,
            "type": "message",
            "model": "cuthair",
            "port": "out",
            "content": "done"
        }
        print(json.dumps(event_data))


def parse_time(time_str):
    """Parse time string in HH:MM:SS:mm format to seconds"""
    h, m, s, ms = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s + ms / 100.0


def main():
    parser = argparse.ArgumentParser(description='Barbershop Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0,
                       help='Total simulation time in seconds (default: 1000000.0)')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create queues for communication between modules
    checkhair_queue = simpy.Store(env)
    cuthair_queue = simpy.Store(env)
    
    # Create modules
    reception = ReceptionDesk(env, checkhair_queue, args.simulation_time)
    checkhair = CheckHair(env, cuthair_queue, checkhair_queue, args.simulation_time)
    cutting = CutHair(env, cuthair_queue, args.simulation_time)
    
    # Process input events from stdin
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
            
        try:
            time_str, event_name = line.split(' ', 1)
            if event_name == 'newcust':
                # Parse time and schedule event
                event_time = parse_time(time_str)
                # Add customer to reception queue
                customer_id = f"cust_{event_time}"
                reception.add_customer(customer_id)
        except ValueError:
            logging.error(f"Invalid input line: {line}")
            continue
    
    # Run simulation
    env.run(until=args.simulation_time)
    
    # Print final state
    final_state = {
        "time": args.simulation_time,
        "type": "state",
        "model": "cuthair",
        "field": "total customer done",
        "value": cutting.total_customer_done
    }
    print(json.dumps(final_state))


if __name__ == "__main__":
    main()