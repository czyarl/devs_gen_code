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
        
        # State tracking
        self.reception_queue_size = 0
        self.checkhair_customer_status = None
        self.cuthair_total_done = 0
        
        # Communication channels (simpy.Store for message passing)
        self.reception_to_checkhair = simpy.Store(env)
        self.checkhair_to_cuthair = simpy.Store(env)
        self.cuthair_to_checkhair = simpy.Store(env)
        self.checkhair_to_reception = simpy.Store(env)
        
        # Resources
        self.reception_resource = simpy.Resource(env, capacity=1)
        self.checkhair_resource = simpy.Resource(env, capacity=1)
        self.cuthair_resource = simpy.Resource(env, capacity=1)
        
        # Initial state output
        self._emit_state("reception", "total customers num", 0)
        self._emit_state("checkhair", "customer", None)
        self._emit_state("cuthair", "total customer done", 0)
    
    def _emit_state(self, model, field, value):
        """Emit a state change event to stdout."""
        output = {
            "time": self.env.now,
            "type": "state",
            "model": model,
            "field": field,
            "value": value
        }
        print(json.dumps(output))
    
    def _emit_message(self, model, port, content):
        """Emit a message event to stdout."""
        output = {
            "time": self.env.now,
            "type": "message",
            "model": model,
            "port": port,
            "content": content
        }
        print(json.dumps(output))
    
    def reception_process(self):
        """Reception desk process - manages customer queue and check-in."""
        # Internal queue to hold customers
        customer_queue = deque()
        
        # Process to handle customer arrivals
        def arrival_handler():
            while True:
                # Wait for customer arrival from input
                customer = yield self.reception_to_checkhair.get()
                
                # Check queue capacity (max 8)
                if len(customer_queue) < 8:
                    # Accept customer and add to queue
                    customer_queue.append(customer)
                    self.reception_queue_size = len(customer_queue)
                    self._emit_state("reception", "total customers num", self.reception_queue_size)
                    logger.info(f"Reception accepted customer at time {self.env.now}, queue size: {self.reception_queue_size}")
                else:
                    # Queue is full, ignore customer
                    logger.info(f"Reception queue full at time {self.env.now}, ignoring customer")
        
        # Start arrival handler
        self.env.process(arrival_handler())
        
        # Main processing loop - continuously process customers from queue
        while True:
            # Wait until there's a customer in the queue
            while len(customer_queue) == 0:
                yield self.env.timeout(0.1)
            
            # Get the first customer from queue (FIFO)
            customer = customer_queue[0]  # Peek at first customer
            
            # Process check-in (5 seconds)
            yield self.env.timeout(5.0)
            
            # Try to send to checkhair
            while True:
                if self.checkhair_resource.count == 0:  # checkhair is available
                    # Send customer to checkhair
                    self._emit_message("reception", "cust", "newcust")
                    yield self.checkhair_to_cuthair.put(customer)
                    # Remove from queue
                    customer_queue.popleft()
                    self.reception_queue_size = len(customer_queue)
                    self._emit_state("reception", "total customers num", self.reception_queue_size)
                    logger.info(f"Reception sent customer to checkhair at time {self.env.now}, queue size: {self.reception_queue_size}")
                    break
                else:
                    # Wait a bit and try again
                    yield self.env.timeout(1.0)
    
    def checkhair_process(self):
        """Hair inspection process - coordinates between reception and cutting."""
        while True:
            # Wait for customer from reception
            customer = yield self.checkhair_to_cuthair.get()
            
            # Update state - processing new customer
            self.checkhair_customer_status = "newcust"
            self._emit_state("checkhair", "customer", "newcust")
            logger.info(f"Checkhair received customer at time {self.env.now}")
            
            # Process consultation (7 seconds)
            yield self.env.timeout(7.0)
            
            # Send to cuthair
            self._emit_message("checkhair", "to_cut", "newcust")
            yield self.cuthair_to_checkhair.put(customer)
            logger.info(f"Checkhair sent customer to cuthair at time {self.env.now}")
            
            # Wait for done signal from cuthair
            done_signal = yield self.cuthair_to_checkhair.get()
            
            # Update state - customer done
            self.checkhair_customer_status = "done"
            self._emit_state("checkhair", "customer", "done")
            logger.info(f"Checkhair received done signal at time {self.env.now}")
            
            # Notify reception that service is complete
            self._emit_message("checkhair", "to_reception", "done")
            yield self.checkhair_to_reception.put("done")
            logger.info(f"Checkhair notified reception at time {self.env.now}")
            
            # Reset state to available
            self.checkhair_customer_status = None
            self._emit_state("checkhair", "customer", None)
    
    def cuthair_process(self):
        """Hair cutting process - executes the haircut."""
        while True:
            # Wait for customer from checkhair
            customer = yield self.cuthair_to_checkhair.get()
            
            logger.info(f"Cuthair received customer at time {self.env.now}")
            
            # Process haircut (20 seconds)
            yield self.env.timeout(20.0)
            
            # Update counter
            self.cuthair_total_done += 1
            self._emit_state("cuthair", "total customer done", self.cuthair_total_done)
            logger.info(f"Cuthair finished haircut at time {self.env.now}, total done: {self.cuthair_total_done}")
            
            # Signal done to checkhair
            self._emit_message("cuthair", "out", "done")
            yield self.cuthair_to_checkhair.put("done")
    
    def customer_arrival_process(self, arrival_times):
        """Process customer arrivals from input schedule."""
        for arrival_time in arrival_times:
            # Wait until arrival time
            yield self.env.timeout(arrival_time - self.env.now)
            
            # Send customer to reception
            yield self.reception_to_checkhair.put("newcust")
            logger.info(f"Customer arrived at time {self.env.now}")
    
    def run(self, arrival_times):
        """Run the simulation."""
        # Start all processes
        self.env.process(self.reception_process())
        self.env.process(self.checkhair_process())
        self.env.process(self.cuthair_process())
        self.env.process(self.customer_arrival_process(arrival_times))
        
        # Run simulation
        logger.info(f"Starting simulation for {self.simulation_time} seconds")
        self.env.run(until=self.simulation_time)
        logger.info("Simulation completed")


def parse_time(time_str):
    """Parse time string HH:MM:SS:mm to seconds."""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def parse_input():
    """Parse input from stdin to get customer arrival schedule."""
    arrival_times = []
    
    logger.info("Reading input from stdin...")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split()
        if len(parts) != 2:
            logger.warning(f"Invalid input line: {line}")
            continue
        
        time_str, event = parts
        if event != "newcust":
            logger.warning(f"Unknown event type: {event}")
            continue
        
        arrival_time = parse_time(time_str)
        arrival_times.append(arrival_time)
        logger.info(f"Scheduled customer arrival at {time_str} ({arrival_time} seconds)")
    
    # Sort arrival times
    arrival_times.sort()
    logger.info(f"Total customers scheduled: {len(arrival_times)}")
    
    return arrival_times


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Barbershop Discrete Event Simulation')
    parser.add_argument(
        '--simulation_time',
        type=float,
        default=1000000.0,
        help='Total simulation time in seconds (default: 1000000.0)'
    )
    
    args = parser.parse_args()
    
    # Parse input from stdin
    arrival_times = parse_input()
    
    # Create and run simulation
    env = simpy.Environment()
    sim = BarbershopSimulation(env, args.simulation_time)
    sim.run(arrival_times)


if __name__ == "__main__":
    main()