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
    """Main simulation class coordinating all modules."""
    
    def __init__(self, simulation_time):
        self.env = simpy.Environment()
        self.simulation_time = simulation_time
        
        # Communication channels (simpy.Store for message passing)
        self.reception_to_checkhair = simpy.Store(self.env)
        self.checkhair_to_cuthair = simpy.Store(self.env)
        self.cuthair_to_checkhair = simpy.Store(self.env)
        self.checkhair_to_reception = simpy.Store(self.env)
        
        # Module instances
        self.reception = Reception(self.env, self)
        self.checkhair = Checkhair(self.env, self)
        self.cuthair = Cuthair(self.env, self)
        
        # Customer arrival events from stdin
        self.arrival_events = []
        
    def parse_time(self, time_str):
        """Parse HH:MM:SS:mm format to seconds."""
        parts = time_str.split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = int(parts[2])
        milliseconds = int(parts[3])
        return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
    
    def read_input(self):
        """Read all input lines from stdin to build initial event schedule."""
        logger.info("Reading input from stdin...")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) >= 2:
                time_str = parts[0]
                event_name = parts[1]
                if event_name == 'newcust':
                    arrival_time = self.parse_time(time_str)
                    self.arrival_events.append((arrival_time, event_name))
        
        # Sort by arrival time
        self.arrival_events.sort(key=lambda x: x[0])
        logger.info(f"Read {len(self.arrival_events)} customer arrival events")
    
    def output_event(self, event):
        """Output event to stdout as JSONL."""
        print(json.dumps(event))
    
    def run(self):
        """Run the simulation."""
        logger.info("Starting barbershop simulation...")
        
        # Start module processes (checkhair and cuthair run continuously)
        self.env.process(self.checkhair.run())
        self.env.process(self.cuthair.run())
        
        # Schedule customer arrivals
        for arrival_time, event_name in self.arrival_events:
            self.env.process(self.customer_arrival(arrival_time, event_name))
        
        # Run simulation
        self.env.run(until=self.simulation_time)
        
        logger.info("Simulation completed.")
    
    def customer_arrival(self, arrival_time, event_name):
        """Process customer arrival at specified time."""
        yield self.env.timeout(arrival_time - self.env.now)
        logger.info(f"Time {self.env.now:.2f}: Customer arrived")
        self.reception.add_customer(event_name)


class Reception:
    """Reception desk module - manages waiting area and check-in."""
    
    def __init__(self, env, simulation):
        self.env = env
        self.sim = simulation
        self.queue = deque()
        self.max_capacity = 8
        self.process_time = 5.0
        self.total_customers = 0
        self.processing = False
    
    def add_customer(self, customer):
        """Add customer to queue if capacity allows."""
        if len(self.queue) < self.max_capacity:
            self.queue.append(customer)
            self.total_customers += 1
            logger.info(f"Reception: Customer added to queue. Queue size: {len(self.queue)}")
            self.sim.output_event({
                "time": self.env.now,
                "type": "state",
                "model": "reception",
                "field": "total customers num",
                "value": self.total_customers
            })
            
            # Start processing if not already processing
            if not self.processing:
                self.env.process(self.process_queue())
        else:
            logger.info(f"Reception: Queue full (8), customer ignored")
    
    def process_queue(self):
        """Process customers in the queue."""
        self.processing = True
        
        while self.queue:
            customer = self.queue[0]  # Peek at first customer
            
            # Hold for 5 seconds (check-in time) - only once per customer
            logger.info(f"Reception: Processing customer for 5 seconds")
            yield self.env.timeout(self.process_time)
            
            # Wait for checkhair to become available
            while not self.sim.checkhair.is_available():
                logger.info(f"Reception: Checkhair busy, waiting...")
                yield self.env.timeout(1.0)
            
            # Remove from queue and send to checkhair
            self.queue.popleft()
            
            # Send message
            logger.info(f"Reception: Sending customer to checkhair")
            self.sim.output_event({
                "time": self.env.now,
                "type": "message",
                "model": "reception",
                "port": "cust",
                "content": "newcust"
            })
            yield self.sim.reception_to_checkhair.put(customer)
        
        self.processing = False
    
    def receive_done(self):
        """Receive done signal from checkhair."""
        logger.info(f"Reception: Received done signal from checkhair")
        # Update state to reflect completion
        self.sim.output_event({
            "time": self.env.now,
            "type": "state",
            "model": "reception",
            "field": "total customers num",
            "value": self.total_customers
        })


class Checkhair:
    """Hair inspection phase - coordinates between reception and cutting."""
    
    def __init__(self, env, simulation):
        self.env = env
        self.sim = simulation
        self.process_time = 7.0
        self.available = True
        self.current_customer = None
    
    def is_available(self):
        """Check if module is available to accept new customer."""
        return self.available
    
    def run(self):
        """Main process loop."""
        while True:
            # Wait for customer from reception
            customer = yield self.sim.reception_to_checkhair.get()
            
            # Mark as busy
            self.available = False
            self.current_customer = customer
            
            logger.info(f"Checkhair: Received customer, processing for 7 seconds")
            self.sim.output_event({
                "time": self.env.now,
                "type": "state",
                "model": "checkhair",
                "field": "customer",
                "value": "newcust"
            })
            
            # Hold for 7 seconds (consultation time)
            yield self.env.timeout(self.process_time)
            
            # Send to cuthair
            logger.info(f"Checkhair: Sending customer to cuthair")
            self.sim.output_event({
                "time": self.env.now,
                "type": "message",
                "model": "checkhair",
                "port": "to_cut",
                "content": "newcust"
            })
            yield self.sim.checkhair_to_cuthair.put(customer)
            
            # Wait for done signal from cuthair
            done_signal = yield self.sim.cuthair_to_checkhair.get()
            
            logger.info(f"Checkhair: Received done signal from cuthair")
            self.sim.output_event({
                "time": self.env.now,
                "type": "state",
                "model": "checkhair",
                "field": "customer",
                "value": "done"
            })
            
            # Send done signal to reception
            logger.info(f"Checkhair: Sending done signal to reception")
            self.sim.output_event({
                "time": self.env.now,
                "type": "message",
                "model": "checkhair",
                "port": "to_reception",
                "content": "done"
            })
            yield self.sim.checkhair_to_reception.put("done")
            
            # Mark as available again
            self.available = True
            self.current_customer = None


class Cuthair:
    """Hair cutting phase - executes the haircut."""
    
    def __init__(self, env, simulation):
        self.env = env
        self.sim = simulation
        self.process_time = 20.0
        self.total_done = 0
    
    def run(self):
        """Main process loop."""
        while True:
            # Wait for customer from checkhair
            customer = yield self.sim.checkhair_to_cuthair.get()
            
            logger.info(f"Cuthair: Received customer, processing for 20 seconds")
            
            # Hold for 20 seconds (cutting time)
            yield self.env.timeout(self.process_time)
            
            # Increment counter
            self.total_done += 1
            logger.info(f"Cuthair: Finished cutting customer. Total done: {self.total_done}")
            self.sim.output_event({
                "time": self.env.now,
                "type": "state",
                "model": "cuthair",
                "field": "total customer done",
                "value": self.total_done
            })
            
            # Send done signal to checkhair
            logger.info(f"Cuthair: Sending done signal to checkhair")
            self.sim.output_event({
                "time": self.env.now,
                "type": "message",
                "model": "cuthair",
                "port": "out",
                "content": "done"
            })
            yield self.sim.cuthair_to_checkhair.put("done")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Barbershop Discrete Event Simulation')
    parser.add_argument(
        '--simulation_time',
        type=float,
        default=1000000.0,
        help='Total simulation time in seconds'
    )
    
    args = parser.parse_args()
    
    # Create and run simulation
    sim = BarbershopSimulation(args.simulation_time)
    sim.read_input()
    sim.run()


if __name__ == '__main__':
    main()