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


class BarbershopSimulation:
    """Main simulation class for the barbershop system."""
    
    def __init__(self, env, simulation_time):
        self.env = env
        self.simulation_time = simulation_time
        
        # Reception state
        self.reception_queue = deque()
        self.reception_capacity = 8
        self.reception_total_customers = 0
        
        # Checkhair state
        self.checkhair_customer = None
        self.checkhair_available = True
        
        # Cuthair state
        self.cuthair_total_done = 0
        
        # Events for coordination
        self.checkhair_done_event = None  # Event triggered when cuthair finishes
        self.reception_done_event = None  # Event triggered when checkhair notifies reception
        
        # Resources
        self.reception_resource = simpy.Resource(env, capacity=1)
        self.checkhair_resource = simpy.Resource(env, capacity=1)
        self.cuthair_resource = simpy.Resource(env, capacity=1)
        
        # Customer counter for tracking
        self.customer_counter = 0
    
    def emit_state(self, model, field, value):
        """Emit a state change event to stdout."""
        output = {
            "time": self.env.now,
            "type": "state",
            "model": model,
            "field": field,
            "value": value
        }
        print(json.dumps(output))
    
    def emit_message(self, model, port, content):
        """Emit a message event to stdout."""
        output = {
            "time": self.env.now,
            "type": "message",
            "model": model,
            "port": port,
            "content": content
        }
        print(json.dumps(output))
    
    def customer_arrival(self, arrival_time):
        """Process customer arrival at reception."""
        yield self.env.timeout(arrival_time - self.env.now)
        
        # Check if queue has capacity
        if len(self.reception_queue) < self.reception_capacity:
            self.customer_counter += 1
            customer_id = self.customer_counter
            self.reception_queue.append(customer_id)
            self.reception_total_customers = len(self.reception_queue)
            self.emit_state("reception", "total customers num", self.reception_total_customers)
            logger.info(f"Customer {customer_id} arrived at {self.env.now}, queue size: {len(self.reception_queue)}")
            
            # Start processing this customer
            self.env.process(self.reception_process(customer_id))
        else:
            logger.info(f"Customer rejected at {self.env.now}, queue full (8)")
    
    def reception_process(self, customer_id):
        """Process customer at reception desk."""
        # Wait for reception resource (1 at a time)
        with self.reception_resource.request() as req:
            yield req
            
            # Check if customer is still in queue (might have been processed)
            if customer_id not in self.reception_queue:
                return
            
            # Hold for 5 seconds (check-in time)
            yield self.env.timeout(5.0)
            
            # Try to send to checkhair
            while True:
                if self.checkhair_available:
                    # Remove from queue
                    if customer_id in self.reception_queue:
                        self.reception_queue.remove(customer_id)
                        self.reception_total_customers = len(self.reception_queue)
                        self.emit_state("reception", "total customers num", self.reception_total_customers)
                    
                    # Send to checkhair
                    self.emit_message("reception", "cust", "newcust")
                    logger.info(f"Reception sent customer {customer_id} to checkhair at {self.env.now}")
                    
                    # Start checkhair process
                    self.env.process(self.checkhair_process(customer_id))
                    break
                else:
                    # Wait a bit and try again
                    yield self.env.timeout(0.1)
    
    def checkhair_process(self, customer_id):
        """Process customer at hair inspection phase."""
        # Mark checkhair as busy
        self.checkhair_available = False
        self.checkhair_customer = "newcust"
        self.emit_state("checkhair", "customer", "newcust")
        logger.info(f"Checkhair started processing customer {customer_id} at {self.env.now}")
        
        # Hold for 7 seconds (consultation time)
        yield self.env.timeout(7.0)
        
        # Send to cuthair
        self.emit_message("checkhair", "to_cut", "newcust")
        logger.info(f"Checkhair sent customer {customer_id} to cuthair at {self.env.now}")
        
        # Start cuthair process
        self.env.process(self.cuthair_process(customer_id))
        
        # Wait for cuthair to finish
        self.checkhair_done_event = self.env.event()
        yield self.checkhair_done_event
        
        # Notify reception that service is complete
        self.emit_message("checkhair", "to_reception", "done")
        logger.info(f"Checkhair notified reception that customer {customer_id} is done at {self.env.now}")
        
        # Mark checkhair as available again
        self.checkhair_customer = "done"
        self.emit_state("checkhair", "customer", "done")
        self.checkhair_available = True
        logger.info(f"Checkhair is now available at {self.env.now}")
    
    def cuthair_process(self, customer_id):
        """Process customer at hair cutting phase."""
        logger.info(f"Cuthair started processing customer {customer_id} at {self.env.now}")
        
        # Hold for 20 seconds (cutting time)
        yield self.env.timeout(20.0)
        
        # Signal done to checkhair
        self.emit_message("cuthair", "out", "done")
        logger.info(f"Cuthair finished customer {customer_id} at {self.env.now}")
        
        # Update counter
        self.cuthair_total_done += 1
        self.emit_state("cuthair", "total customer done", self.cuthair_total_done)
        
        # Trigger checkhair done event
        if self.checkhair_done_event:
            self.checkhair_done_event.succeed()


def parse_time(time_str):
    """Parse time string HH:MM:SS:mm to seconds."""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def read_input_schedule():
    """Read customer arrival schedule from stdin."""
    arrivals = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            time_str = parts[0]
            event_name = parts[1]
            if event_name == "newcust":
                arrival_time = parse_time(time_str)
                arrivals.append(arrival_time)
    return arrivals


def main():
    """Main entry point for the simulation."""
    parser = argparse.ArgumentParser(description='Barbershop Discrete Event Simulation')
    parser.add_argument(
        '--simulation_time',
        type=float,
        default=1000000.0,
        help='Total simulation time in seconds'
    )
    args = parser.parse_args()
    
    logger.info(f"Starting barbershop simulation with max time: {args.simulation_time}")
    
    # Read input schedule
    arrivals = read_input_schedule()
    logger.info(f"Read {len(arrivals)} customer arrivals from stdin")
    
    # Create simulation environment
    env = simpy.Environment()
    sim = BarbershopSimulation(env, args.simulation_time)
    
    # Schedule customer arrivals
    for arrival_time in arrivals:
        env.process(sim.customer_arrival(arrival_time))
    
    # Run simulation
    logger.info("Running simulation...")
    env.run(until=args.simulation_time)
    
    logger.info(f"Simulation completed at time {env.now}")
    logger.info(f"Total customers processed by cuthair: {sim.cuthair_total_done}")


if __name__ == "__main__":
    main()