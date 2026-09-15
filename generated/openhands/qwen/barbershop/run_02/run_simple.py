#!/usr/bin/env python3
"""
Simple Barbershop Simulation using Discrete Event Simulation (DES) with SimPy
"""

import argparse
import sys
import json
import logging
import simpy


# Global logger for debug output
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)


class ReceptionDesk:
    """Reception desk module for barbershop simulation"""
    
    def __init__(self, env, checkhair_queue, cuthair_queue):
        self.env = env
        self.checkhair_queue = checkhair_queue
        self.cuthair_queue = cuthair_queue
        self.queue = []
        self.total_customers = 0
        self.capacity = 8
        self.processing_time = 5.0  # seconds
        
    def process_customer(self):
        """Process customers in the reception queue"""
        while True:
            if self.queue:
                # Process the first customer in queue
                customer = self.queue[0]
                logger.debug(f"Reception: Processing customer {customer} at time {self.env.now}")
                
                # Emit state change for total customers
                self.emit_state_change("reception", "total customers num", len(self.queue))
                
                # Wait for 5 seconds to process customer
                yield self.env.timeout(self.processing_time)
                
                # Check if checkhair is available (queue has space)
                if len(self.checkhair_queue.items) < self.checkhair_queue.capacity:
                    # Send customer to hair inspection
                    logger.debug(f"Reception: Sending customer {customer} to checkhair at time {self.env.now}")
                    self.checkhair_queue.put(customer)
                    self.queue.pop(0)
                    self.emit_message("reception", "cust", "newcust")
                else:
                    # Wait until checkhair is available
                    logger.debug(f"Reception: Checkhair busy, waiting for customer {customer} at time {self.env.now}")
                    # We'll handle this in the next iteration
                    yield self.env.timeout(0.1)  # Small delay to allow other processes
            else:
                yield self.env.timeout(0.1)  # Small delay when no customers
    
    def emit_state_change(self, model, field, value):
        """Emit a state change event"""
        event = {
            "time": self.env.now,
            "type": "state",
            "model": model,
            "field": field,
            "value": value
        }
        print(json.dumps(event))
        sys.stdout.flush()
    
    def emit_message(self, model, port, content):
        """Emit a message event"""
        event = {
            "time": self.env.now,
            "type": "message",
            "model": model,
            "port": port,
            "content": content
        }
        print(json.dumps(event))
        sys.stdout.flush()
    
    def add_customer(self, customer):
        """Add a customer to the reception queue if space is available"""
        if len(self.queue) < self.capacity:
            self.queue.append(customer)
            self.total_customers += 1
            logger.debug(f"Reception: Added customer {customer}, queue size: {len(self.queue)}")
            self.emit_state_change("reception", "total customers num", len(self.queue))
        else:
            logger.debug(f"Reception: Queue full, ignoring customer {customer}")


class HairInspection:
    """Hair inspection phase module"""
    
    def __init__(self, env, cuthair_queue):
        self.env = env
        self.cuthair_queue = cuthair_queue
        self.customer = None
        self.processing_time = 7.0  # seconds
        
    def process_customer(self):
        """Process customers in the hair inspection phase"""
        while True:
            # Wait for a customer from reception
            customer = yield self.cuthair_queue.get()
            self.customer = customer
            logger.debug(f"Checkhair: Processing customer {customer} at time {self.env.now}")
            
            # Emit state change for customer being processed
            self.emit_state_change("checkhair", "customer", "newcust")
            
            # Wait for 7 seconds to process customer
            yield self.env.timeout(self.processing_time)
            
            # Send customer to hair cutting
            logger.debug(f"Checkhair: Sending customer {customer} to cuthair at time {self.env.now}")
            self.cuthair_queue.put(customer)
            self.emit_message("checkhair", "to_cut", "newcust")
            
            # Wait for completion signal from cutting phase
            logger.debug(f"Checkhair: Waiting for completion signal from cuthair for customer {customer}")
            # In a real implementation, we'd wait for a signal from cuthair
            # For now, we'll simulate by yielding a small delay
            yield self.env.timeout(0.1)  # Placeholder for actual signal handling
            
            # Emit completion signal back to reception
            logger.debug(f"Checkhair: Sending completion signal to reception for customer {customer}")
            self.emit_message("checkhair", "to_reception", "done")
            
            # Reset customer status
            self.customer = None
            self.emit_state_change("checkhair", "customer", "done")
    
    def emit_state_change(self, model, field, value):
        """Emit a state change event"""
        event = {
            "time": self.env.now,
            "type": "state",
            "model": model,
            "field": field,
            "value": value
        }
        print(json.dumps(event))
        sys.stdout.flush()
    
    def emit_message(self, model, port, content):
        """Emit a message event"""
        event = {
            "time": self.env.now,
            "type": "message",
            "model": model,
            "port": port,
            "content": content
        }
        print(json.dumps(event))
        sys.stdout.flush()


class HairCutting:
    """Hair cutting phase module"""
    
    def __init__(self, env):
        self.env = env
        self.total_customer_done = 0
        self.processing_time = 20.0  # seconds
        
    def process_customer(self):
        """Process customers in the hair cutting phase"""
        while True:
            # Wait for a customer from hair inspection
            # This is the key part - we need to wait for a customer from the queue
            customer = yield self.env.timeout(0.1)  # Placeholder - we'll fix this
            
            # In a real implementation, we'd wait for a customer from the queue
            # For now, we'll just simulate the process
            logger.debug(f"Cuthair: Processing customer at time {self.env.now}")
            
            # Wait for 20 seconds to cut hair
            yield self.env.timeout(self.processing_time)
            
            # Signal completion back to hair inspection
            logger.debug(f"Cuthair: Customer cutting complete at time {self.env.now}")
            self.total_customer_done += 1
            self.emit_state_change("cuthair", "total customer done", self.total_customer_done)
            self.emit_message("cuthair", "out", "done")
    
    def emit_state_change(self, model, field, value):
        """Emit a state change event"""
        event = {
            "time": self.env.now,
            "type": "state",
            "model": model,
            "field": field,
            "value": value
        }
        print(json.dumps(event))
        sys.stdout.flush()
    
    def emit_message(self, model, port, content):
        """Emit a message event"""
        event = {
            "time": self.env.now,
            "type": "message",
            "model": model,
            "port": port,
            "content": content
        }
        print(json.dumps(event))
        sys.stdout.flush()


def parse_time(time_str):
    """Parse time string in HH:MM:SS:mm format to seconds"""
    h, m, s, ms = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s + ms / 100.0


def main():
    parser = argparse.ArgumentParser(description='Barbershop Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0, 
                       help='Total simulation time in seconds (default: 1000000.0)')
    
    args = parser.parse_args()
    
    # Read input events from stdin
    events = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            time_str, event_name = line.split(' ', 1)
            if event_name == 'newcust':
                time_seconds = parse_time(time_str)
                events.append((time_seconds, event_name))
        except ValueError:
            logger.warning(f"Skipping invalid line: {line}")
    
    # Sort events by time
    events.sort(key=lambda x: x[0])
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create queues for communication between modules
    checkhair_queue = simpy.Store(env, capacity=1)  # Only one customer at a time in inspection
    cuthair_queue = simpy.Store(env, capacity=1)   # Only one customer at a time in cutting
    
    # Create modules
    reception = ReceptionDesk(env, checkhair_queue, cuthair_queue)
    checkhair = HairInspection(env, cuthair_queue)
    cuthair = HairCutting(env)
    
    # Schedule customer arrivals at the correct times
    for time_seconds, event_name in events:
        if event_name == 'newcust':
            # Schedule customer arrival at the specified time
            def schedule_customer_arrival():
                yield env.timeout(time_seconds)
                reception.add_customer("customer")
            
            env.process(schedule_customer_arrival())
    
    # Start processing
    env.process(reception.process_customer())
    env.process(checkhair.process_customer())
    env.process(cuthair.process_customer())
    
    # Run simulation
    logger.debug(f"Starting simulation for {args.simulation_time} seconds")
    env.run(until=args.simulation_time)
    
    logger.debug("Simulation completed")


if __name__ == "__main__":
    main()