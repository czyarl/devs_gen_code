#!/usr/bin/env python3
"""
Barbershop Discrete Event Simulation
Simulates customer flow through reception, hair inspection, and hair cutting phases.
"""

import argparse
import sys
import json
import logging
from collections import deque
import simpy

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


class OutputLogger:
    """Handles JSONL output to stdout."""
    
    def __init__(self):
        self.lock = simpy.Resource(simpy.Environment(), capacity=1)
    
    def log_state(self, time, model, field, value):
        """Log a state change event."""
        output = {
            "time": time,
            "type": "state",
            "model": model,
            "field": field,
            "value": value
        }
        print(json.dumps(output))
    
    def log_message(self, time, model, port, content):
        """Log a message event."""
        output = {
            "time": time,
            "type": "message",
            "model": model,
            "port": port,
            "content": content
        }
        print(json.dumps(output))


class ReceptionDesk:
    """Reception desk module - manages customer queue and check-in."""
    
    def __init__(self, env, output_logger, to_checkhair, from_checkhair):
        self.env = env
        self.output = output_logger
        self.to_checkhair = to_checkhair  # Store for sending customers to checkhair
        self.from_checkhair = from_checkhair  # Store for receiving done signals
        self.queue = deque()
        self.max_capacity = 8
        self.processing_time = 5.0
        self.total_customers = 0
        self.name = "reception"
    
    def add_customer(self, customer_id):
        """Add a new customer to the queue if capacity allows."""
        if len(self.queue) < self.max_capacity:
            self.queue.append(customer_id)
            self.total_customers = len(self.queue)
            self.output.log_state(self.env.now, self.name, "total customers num", self.total_customers)
            logger.info(f"Time {self.env.now}: Customer {customer_id} added to reception queue. Queue size: {self.total_customers}")
            return True
        else:
            logger.info(f"Time {self.env.now}: Customer {customer_id} rejected - queue full (capacity: {self.max_capacity})")
            return False
    
    def process_queue(self):
        """Process customers in the queue."""
        while True:
            if self.queue:
                customer = self.queue[0]  # Peek at first customer
                logger.info(f"Time {self.env.now}: Reception processing customer {customer}")
                
                # Hold customer for 5 seconds
                yield self.env.timeout(self.processing_time)
                
                # Try to send to checkhair
                if self.to_checkhair.level < 1:  # Check if checkhair is available
                    customer = self.queue.popleft()  # Remove from queue
                    self.total_customers = len(self.queue)
                    self.output.log_state(self.env.now, self.name, "total customers num", self.total_customers)
                    
                    # Send customer to checkhair
                    yield self.to_checkhair.put(customer)
                    self.output.log_message(self.env.now, self.name, "cust", "newcust")
                    logger.info(f"Time {self.env.now}: Customer {customer} sent to checkhair")
                else:
                    logger.info(f"Time {self.env.now}: Customer {customer} waiting - checkhair busy")
            else:
                # Wait a bit before checking again
                yield self.env.timeout(0.1)
    
    def receive_done_signal(self):
        """Receive done signal from checkhair."""
        while True:
            done_signal = yield self.from_checkhair.get()
            logger.info(f"Time {self.env.now}: Reception received done signal from checkhair")


class HairInspection:
    """Hair inspection module - coordinates between reception and cutting."""
    
    def __init__(self, env, output_logger, from_reception, to_cuthair, from_cuthair, to_reception):
        self.env = env
        self.output = output_logger
        self.from_reception = from_reception  # Store for receiving customers
        self.to_cuthair = to_cuthair  # Store for sending to cutting
        self.from_cuthair = from_cuthair  # Store for receiving done signals
        self.to_reception = to_reception  # Store for sending done to reception
        self.processing_time = 7.0
        self.name = "checkhair"
        self.current_customer = None
    
    def process(self):
        """Main processing loop for hair inspection."""
        while True:
            # Wait for customer from reception
            customer = yield self.from_reception.get()
            self.current_customer = customer
            self.output.log_state(self.env.now, self.name, "customer", "newcust")
            logger.info(f"Time {self.env.now}: Checkhair received customer {customer}")
            
            # Process customer for 7 seconds
            yield self.env.timeout(self.processing_time)
            
            # Send customer to cuthair
            yield self.to_cuthair.put(customer)
            self.output.log_message(self.env.now, self.name, "to_cut", "newcust")
            logger.info(f"Time {self.env.now}: Checkhair sent customer {customer} to cuthair")
            
            # Wait for done signal from cuthair
            done_signal = yield self.from_cuthair.get()
            logger.info(f"Time {self.env.now}: Checkhair received done signal from cuthair")
            
            # Send done signal to reception
            yield self.to_reception.put(done_signal)
            self.output.log_message(self.env.now, self.name, "to_reception", "done")
            
            # Update state to done
            self.output.log_state(self.env.now, self.name, "customer", "done")
            logger.info(f"Time {self.env.now}: Checkhair sent done signal to reception")
            
            self.current_customer = None


class HairCutting:
    """Hair cutting module - performs the actual hair cutting."""
    
    def __init__(self, env, output_logger, from_checkhair, to_checkhair):
        self.env = env
        self.output = output_logger
        self.from_checkhair = from_checkhair  # Store for receiving customers
        self.to_checkhair = to_checkhair  # Store for sending done signals
        self.processing_time = 20.0
        self.name = "cuthair"
        self.total_done = 0
    
    def process(self):
        """Main processing loop for hair cutting."""
        while True:
            # Wait for customer from checkhair
            customer = yield self.from_checkhair.get()
            logger.info(f"Time {self.env.now}: Cuthair received customer {customer}")
            
            # Process customer for 20 seconds
            yield self.env.timeout(self.processing_time)
            
            # Increment counter
            self.total_done += 1
            self.output.log_state(self.env.now, self.name, "total customer done", self.total_done)
            
            # Send done signal to checkhair
            yield self.to_checkhair.put("done")
            self.output.log_message(self.env.now, self.name, "out", "done")
            logger.info(f"Time {self.env.now}: Cuthair finished customer {customer}, sent done signal")


def parse_time(time_str):
    """Parse time string HH:MM:SS:mm to seconds."""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def read_input_events():
    """Read all input events from stdin."""
    events = []
    logger.info("Reading input events from stdin...")
    
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split()
        if len(parts) != 2:
            logger.warning(f"Invalid input line: {line}")
            continue
        
        time_str, event_name = parts
        if event_name != "newcust":
            logger.warning(f"Unknown event type: {event_name}")
            continue
        
        time = parse_time(time_str)
        events.append((time, event_name))
    
    logger.info(f"Read {len(events)} input events")
    return events


def main():
    """Main simulation entry point."""
    parser = argparse.ArgumentParser(description='Barbershop Discrete Event Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0,
                        help='Total simulation time in seconds')
    args = parser.parse_args()
    
    logger.info(f"Starting barbershop simulation with max time: {args.simulation_time}")
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create output logger
    output_logger = OutputLogger()
    
    # Create communication channels (Stores with capacity 1 for coordination)
    # reception -> checkhair
    to_checkhair = simpy.Store(env, capacity=1)
    # checkhair -> reception (done signals)
    to_reception = simpy.Store(env, capacity=1)
    # checkhair -> cuthair
    to_cuthair = simpy.Store(env, capacity=1)
    # cuthair -> checkhair (done signals)
    to_checkhair_done = simpy.Store(env, capacity=1)
    
    # Create modules
    reception = ReceptionDesk(env, output_logger, to_checkhair, to_reception)
    checkhair = HairInspection(env, output_logger, to_checkhair, to_cuthair, to_checkhair_done, to_reception)
    cuthair = HairCutting(env, output_logger, to_cuthair, to_checkhair_done)
    
    # Start module processes
    env.process(reception.process_queue())
    env.process(reception.receive_done_signal())
    env.process(checkhair.process())
    env.process(cuthair.process())
    
    # Read input events and schedule them
    input_events = read_input_events()
    customer_counter = 0
    
    def schedule_customer(arrival_time, customer_id):
        """Schedule a customer arrival at the specified time."""
        yield env.timeout(arrival_time)
        reception.add_customer(customer_id)
    
    for time, event_name in input_events:
        customer_counter += 1
        env.process(schedule_customer(time, customer_counter))
    
    logger.info(f"Scheduled {customer_counter} customer arrivals")
    
    # Run simulation
    logger.info("Running simulation...")
    env.run(until=args.simulation_time)
    
    logger.info(f"Simulation completed at time {env.now}")
    logger.info(f"Total customers processed by cuthair: {cuthair.total_done}")


if __name__ == "__main__":
    main()