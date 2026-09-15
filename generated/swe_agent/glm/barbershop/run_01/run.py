#!/usr/bin/env python3
"""
Barbershop Simulation using Discrete Event Simulation (DES)
Implements a barbershop workflow with Reception, Hair Inspection, and Hair Cutting phases.
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
    """Handles output to stdout (JSONL) and stderr (logging)"""
    
    def __init__(self):
        pass
    
    def log_state(self, time, model, field, value):
        """Log a state change event"""
        output = {
            "time": time,
            "type": "state",
            "model": model,
            "field": field,
            "value": value
        }
        print(json.dumps(output))
    
    def log_message(self, time, model, port, content):
        """Log a communication event"""
        output = {
            "time": time,
            "type": "message",
            "model": model,
            "port": port,
            "content": content
        }
        print(json.dumps(output))


class Reception:
    """Reception Desk - manages customer queue and check-in"""
    
    def __init__(self, env, output_logger, checkhair):
        self.env = env
        self.output = output_logger
        self.checkhair = checkhair
        self.queue = deque()
        self.max_capacity = 8
        self.total_customers = 0
        self.processing = None
        self.resource = simpy.Resource(env, capacity=1)
    
    def add_customer(self, customer_time):
        """Add a new customer to the queue if capacity allows"""
        if len(self.queue) < self.max_capacity:
            self.queue.append(customer_time)
            self.total_customers = len(self.queue)
            self.output.log_state(self.env.now, "reception", "total customers num", self.total_customers)
            logger.info(f"Time {self.env.now}: Customer added to reception queue. Queue size: {len(self.queue)}")
            
            # Start processing if not already processing
            if self.processing is None:
                self.env.process(self.process_queue())
        else:
            logger.info(f"Time {self.env.now}: Customer rejected - queue full (capacity: {self.max_capacity})")
    
    def process_queue(self):
        """Process customers in the queue"""
        while self.queue:
            self.processing = True
            customer = self.queue[0]  # Peek at first customer
            
            # Hold for 5 seconds (check-in time)
            yield self.env.timeout(5.0)
            
            # Try to send to checkhair
            if self.checkhair.is_available():
                # Remove from queue
                self.queue.popleft()
                self.total_customers = len(self.queue)
                self.output.log_state(self.env.now, "reception", "total customers num", self.total_customers)
                
                # Send message to checkhair
                self.output.log_message(self.env.now, "reception", "cust", "newcust")
                self.checkhair.receive_customer(self.env.now)
                logger.info(f"Time {self.env.now}: Customer sent to checkhair. Queue size: {len(self.queue)}")
            else:
                # Wait and try again
                logger.info(f"Time {self.env.now}: Checkhair busy, customer waiting")
                yield self.env.timeout(1.0)
        
        self.processing = None
    
    def notify_complete(self):
        """Receive notification that service is complete"""
        # This is called when checkhair sends a completion notification
        # The queue processing continues automatically
        pass


class CheckHair:
    """Hair Inspection Phase - coordinates between reception and cutting"""
    
    def __init__(self, env, output_logger, cuthair, reception):
        self.env = env
        self.output = output_logger
        self.cuthair = cuthair
        self.reception = reception
        self.available = True
        self.current_customer = None
        self.waiting_for_done = False
    
    def is_available(self):
        """Check if this phase is available to accept a new customer"""
        return self.available
    
    def receive_customer(self, customer_time):
        """Receive a customer from reception"""
        if self.available:
            self.available = False
            self.current_customer = "newcust"
            self.output.log_state(self.env.now, "checkhair", "customer", "newcust")
            logger.info(f"Time {self.env.now}: Checkhair received customer")
            
            # Start processing
            self.env.process(self.process_customer())
        else:
            logger.warning(f"Time {self.env.now}: Checkhair received customer but not available!")
    
    def process_customer(self):
        """Process the customer through inspection phase"""
        # Hold for 7 seconds (consultation time)
        yield self.env.timeout(7.0)
        
        # Send to cuthair
        self.output.log_message(self.env.now, "checkhair", "to_cut", "newcust")
        self.cuthair.receive_customer(self.env.now)
        logger.info(f"Time {self.env.now}: Customer sent to cuthair")
        
        # Wait for done signal from cuthair
        self.waiting_for_done = True
        yield self.env.process(self.wait_for_cuthair_done())
        
        # After receiving done, notify reception
        self.output.log_message(self.env.now, "checkhair", "to_reception", "done")
        self.reception.notify_complete()
        logger.info(f"Time {self.env.now}: Checkhair notified reception of completion")
        
        # Become available again
        self.current_customer = "done"
        self.output.log_state(self.env.now, "checkhair", "customer", "done")
        self.available = True
        self.waiting_for_done = False
        self.current_customer = None
    
    def wait_for_cuthair_done(self):
        """Wait for the done signal from cuthair"""
        # This is a blocking wait that will be triggered by cuthair
        while self.waiting_for_done:
            yield self.env.timeout(0.1)
    
    def receive_done(self):
        """Receive done signal from cuthair"""
        self.waiting_for_done = False


class CutHair:
    """Hair Cutting Phase - executes the hair cutting"""
    
    def __init__(self, env, output_logger, checkhair):
        self.env = env
        self.output = output_logger
        self.checkhair = checkhair
        self.total_done = 0
    
    def receive_customer(self, customer_time):
        """Receive a customer from checkhair"""
        logger.info(f"Time {self.env.now}: Cuthair received customer")
        
        # Start processing
        self.env.process(self.process_customer())
    
    def process_customer(self):
        """Process the customer through cutting phase"""
        # Hold for 20 seconds (cutting time)
        yield self.env.timeout(20.0)
        
        # Increment counter
        self.total_done += 1
        self.output.log_state(self.env.now, "cuthair", "total customer done", self.total_done)
        
        # Send done signal to checkhair
        self.output.log_message(self.env.now, "cuthair", "out", "done")
        self.checkhair.receive_done()
        logger.info(f"Time {self.env.now}: Cuthair finished customer. Total done: {self.total_done}")


def parse_time(time_str):
    """Parse time string HH:MM:SS:mm to seconds"""
    parts = time_str.split(':')
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {time_str}")
    
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    
    # Calculate total seconds from the start of the day
    total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 100.0
    
    # Find the minimum time and subtract it to make times relative to simulation start
    return total_seconds


def read_input_schedule():
    """Read all input lines from stdin and build event schedule"""
    schedule = []
    
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split()
        if len(parts) != 2:
            logger.warning(f"Skipping invalid line: {line}")
            continue
        
        time_str, event_name = parts
        
        if event_name != "newcust":
            logger.warning(f"Skipping unknown event: {event_name}")
            continue
        
        try:
            time = parse_time(time_str)
            schedule.append((time, event_name))
        except ValueError as e:
            logger.warning(f"Skipping invalid time: {time_str} - {e}")
    
    # Sort by time
    schedule.sort(key=lambda x: x[0])
    
    # Normalize times to start from 0
    if schedule:
        min_time = schedule[0][0]
        schedule = [(time - min_time, event_name) for time, event_name in schedule]
    
    logger.info(f"Read {len(schedule)} events from input")
    
    return schedule


def run_simulation(simulation_time):
    """Run the barbershop simulation"""
    # Create SimPy environment
    env = simpy.Environment()
    
    # Create output logger
    output_logger = OutputLogger()
    
    # Create modules
    cuthair = CutHair(env, output_logger, None)
    checkhair = CheckHair(env, output_logger, cuthair, None)
    reception = Reception(env, output_logger, checkhair)
    
    # Link modules
    cuthair.checkhair = checkhair
    checkhair.reception = reception
    
    # Read input schedule
    schedule = read_input_schedule()
    
    # Schedule customer arrivals
    for time, event_name in schedule:
        env.process(customer_arrival(env, reception, time))
    
    # Run simulation
    logger.info(f"Starting simulation for {simulation_time} seconds")
    env.run(until=simulation_time)
    logger.info("Simulation completed")


def customer_arrival(env, reception, arrival_time):
    """Process a customer arrival at the specified time"""
    yield env.timeout(arrival_time)
    reception.add_customer(arrival_time)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description='Barbershop Simulation')
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
        sys.exit(1)


if __name__ == '__main__':
    main()
