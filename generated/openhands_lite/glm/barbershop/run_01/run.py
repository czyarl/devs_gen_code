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


def parse_time(time_str):
    """Parse HH:MM:SS:mm format to seconds."""
    parts = time_str.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0


def emit_state(time, model, field, value):
    """Emit a state change event to stdout."""
    output = {
        "time": time,
        "type": "state",
        "model": model,
        "field": field,
        "value": value
    }
    print(json.dumps(output))


def emit_message(time, model, port, content):
    """Emit a communication event to stdout."""
    output = {
        "time": time,
        "type": "message",
        "model": model,
        "port": port,
        "content": content
    }
    print(json.dumps(output))


class Reception:
    """Reception desk module - manages customer queue and check-in."""
    
    def __init__(self, env, checkhair):
        self.env = env
        self.checkhair = checkhair
        self.queue = deque()
        self.max_capacity = 8
        self.processing_time = 5.0
        self.total_customers = 0
        self.customer_counter = 0
        
    def add_customer(self, arrival_time):
        """Add a customer to the queue if capacity allows."""
        if len(self.queue) < self.max_capacity:
            self.queue.append(arrival_time)
            self.total_customers += 1
            emit_state(self.env.now, "reception", "total customers num", self.total_customers)
            logger.info(f"Time {self.env.now}: Customer added to reception queue. Total: {self.total_customers}")
            return True
        else:
            logger.info(f"Time {self.env.now}: Customer rejected - queue full (capacity: {self.max_capacity})")
            return False
    
    def process_queue(self):
        """Process customers from the queue."""
        while True:
            if self.queue:
                # Get first customer
                customer_arrival = self.queue[0]
                
                # Process for 5 seconds
                yield self.env.timeout(self.processing_time)
                
                # Try to send to checkhair
                if self.checkhair.is_available():
                    self.queue.popleft()
                    emit_message(self.env.now, "reception", "cust", "newcust")
                    logger.info(f"Time {self.env.now}: Customer sent to checkhair")
                    
                    # Trigger checkhair to process
                    self.checkhair.receive_customer()
                else:
                    # Wait and try again
                    logger.info(f"Time {self.env.now}: Checkhair busy, customer waiting")
                    yield self.env.timeout(1.0)
            else:
                # No customers, wait a bit
                yield self.env.timeout(0.1)
    
    def notify_complete(self):
        """Called when a customer completes full service."""
        logger.info(f"Time {self.env.now}: Reception notified of service completion")


class CheckHair:
    """Hair inspection phase - coordinates between reception and cutting."""
    
    def __init__(self, env, cuthair, reception):
        self.env = env
        self.cuthair = cuthair
        self.reception = reception
        self.processing_time = 7.0
        self.available = True
        self.current_customer = None
        self.waiting_for_done = False
        
    def is_available(self):
        """Check if available to accept new customer."""
        return self.available and not self.waiting_for_done
    
    def receive_customer(self):
        """Receive customer from reception."""
        if self.is_available():
            self.available = False
            self.current_customer = "newcust"
            emit_state(self.env.now, "checkhair", "customer", "newcust")
            logger.info(f"Time {self.env.now}: Checkhair received customer")
            
            # Start processing
            self.env.process(self._process_customer())
    
    def _process_customer(self):
        """Process customer through inspection phase."""
        # Hold for 7 seconds
        yield self.env.timeout(self.processing_time)
        
        # Send to cuthair
        emit_message(self.env.now, "checkhair", "to_cut", "newcust")
        logger.info(f"Time {self.env.now}: Checkhair sent customer to cuthair")
        
        # Trigger cuthair
        self.cuthair.receive_customer()
        
        # Wait for done signal from cuthair
        self.waiting_for_done = True
        logger.info(f"Time {self.env.now}: Checkhair waiting for done signal")
    
    def receive_done(self):
        """Receive done signal from cuthair."""
        logger.info(f"Time {self.env.now}: Checkhair received done signal")
        
        # Send notification back to reception
        emit_message(self.env.now, "checkhair", "to_reception", "done")
        self.reception.notify_complete()
        
        # Update state
        self.current_customer = "done"
        emit_state(self.env.now, "checkhair", "customer", "done")
        
        # Reset to available
        self.waiting_for_done = False
        self.available = True
        self.current_customer = None
        logger.info(f"Time {self.env.now}: Checkhair now available")


class CutHair:
    """Hair cutting phase - executes the haircut."""
    
    def __init__(self, env, checkhair):
        self.env = env
        self.checkhair = checkhair
        self.processing_time = 20.0
        self.total_done = 0
        self.busy = False
        
    def receive_customer(self):
        """Receive customer from checkhair."""
        if not self.busy:
            self.busy = True
            logger.info(f"Time {self.env.now}: Cuthair received customer")
            self.env.process(self._process_customer())
    
    def _process_customer(self):
        """Process customer through cutting phase."""
        # Hold for 20 seconds
        yield self.env.timeout(self.processing_time)
        
        # Increment counter
        self.total_done += 1
        emit_state(self.env.now, "cuthair", "total customer done", self.total_done)
        logger.info(f"Time {self.env.now}: Cuthair finished customer. Total done: {self.total_done}")
        
        # Send done signal to checkhair
        emit_message(self.env.now, "cuthair", "out", "done")
        self.checkhair.receive_done()
        
        # Reset
        self.busy = False


def read_input_schedule():
    """Read all input from stdin and build event schedule."""
    schedule = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            time_str = parts[0]
            event_name = parts[1]
            if event_name == "newcust":
                time_seconds = parse_time(time_str)
                schedule.append((time_seconds, event_name))
    
    # Sort by time
    schedule.sort(key=lambda x: x[0])
    return schedule


def run_simulation(simulation_time):
    """Run the barbershop simulation."""
    # Create simpy environment
    env = simpy.Environment()
    
    # Create modules
    cuthair = CutHair(env, None)
    checkhair = CheckHair(env, cuthair, None)
    reception = Reception(env, checkhair)
    
    # Link modules
    cuthair.checkhair = checkhair
    checkhair.reception = reception
    
    # Read input schedule
    schedule = read_input_schedule()
    logger.info(f"Read {len(schedule)} customer arrivals from input")
    
    # Schedule customer arrivals
    for arrival_time, event_name in schedule:
        env.process(arrival_process(env, reception, arrival_time))
    
    # Start reception processing
    env.process(reception.process_queue())
    
    # Run simulation
    logger.info(f"Starting simulation for {simulation_time} seconds")
    env.run(until=simulation_time)
    logger.info("Simulation completed")


def arrival_process(env, reception, arrival_time):
    """Process a customer arrival at the specified time."""
    yield env.timeout(arrival_time)
    logger.info(f"Time {env.now}: New customer arrival")
    reception.add_customer(arrival_time)


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
    
    try:
        run_simulation(args.simulation_time)
    except Exception as e:
        logger.error(f"Simulation error: {e}")
        raise


if __name__ == '__main__':
    main()
