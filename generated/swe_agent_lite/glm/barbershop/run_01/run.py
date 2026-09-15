#!/usr/bin/env python3
"""
Barbershop Simulation using Discrete Event Simulation (DES)
Simulates customer flow through Reception, Hair Inspection, and Hair Cutting phases.
"""

import argparse
import sys
import json
import logging
import simpy
from collections import deque
from typing import Optional, Dict, Any

# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


def parse_time(time_str: str) -> float:
    """
    Parse time string HH:MM:SS:mm to seconds.
    
    Args:
        time_str: Time string in format HH:MM:SS:mm
        
    Returns:
        Time in seconds as float
    """
    parts = time_str.split(':')
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {time_str}")
    
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = int(parts[2])
    milliseconds = int(parts[3])
    
    total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 100.0
    return total_seconds


def emit_state(time: float, model: str, field: str, value: Any):
    """
    Emit a state change event to stdout.
    
    Args:
        time: Simulation time
        model: Model name (reception, checkhair, cuthair)
        field: Field name being updated
        value: New value
    """
    output = {
        "time": time,
        "type": "state",
        "model": model,
        "field": field,
        "value": value
    }
    print(json.dumps(output))
    sys.stdout.flush()


def emit_message(time: float, model: str, port: str, content: str):
    """
    Emit a communication event to stdout.
    
    Args:
        time: Simulation time
        model: Sender model name
        port: Communication port name
        content: Message content
    """
    output = {
        "time": time,
        "type": "message",
        "model": model,
        "port": port,
        "content": content
    }
    print(json.dumps(output))
    sys.stdout.flush()


class Reception:
    """
    Reception Desk module.
    - Queue capacity: 8 customers
    - Processing: 1 customer at a time, 5 seconds per customer
    """
    
    def __init__(self, env: simpy.Environment, checkhair: 'CheckHair'):
        self.env = env
        self.checkhair = checkhair
        self.queue = deque()
        self.max_capacity = 8
        self.total_customers = 0
        self.processing = False
        self.customer_arrivals = []  # List of (time, customer_id)
        
    def add_customer(self, customer_id: str):
        """
        Add a customer to the queue if capacity allows.
        
        Args:
            customer_id: Customer identifier
        """
        if len(self.queue) < self.max_capacity:
            self.queue.append(customer_id)
            self.total_customers = len(self.queue)
            emit_state(self.env.now, "reception", "total customers num", self.total_customers)
            logger.info(f"Time {self.env.now}: Customer {customer_id} added to reception queue. Queue size: {len(self.queue)}")
            
            # Start processing if not already processing
            if not self.processing:
                self.env.process(self.process_queue())
        else:
            logger.info(f"Time {self.env.now}: Customer {customer_id} ignored - queue full (capacity: {self.max_capacity})")
    
    def process_queue(self):
        """
        Process customers in the queue.
        """
        self.processing = True
        
        while self.queue:
            customer = self.queue[0]  # Peek at first customer
            
            # Hold customer for 5 seconds (check-in time)
            logger.info(f"Time {self.env.now}: Processing customer {customer} for 5 seconds")
            yield self.env.timeout(5.0)
            
            # After 5 seconds, try to send to checkhair
            # Wait until checkhair is available
            while not self.checkhair.is_available():
                logger.info(f"Time {self.env.now}: Waiting for checkhair to become available")
                yield self.env.timeout(1.0)
            
            # Send customer to checkhair
            logger.info(f"Time {self.env.now}: Sending customer {customer} to checkhair")
            emit_message(self.env.now, "reception", "cust", "newcust")
            self.checkhair.receive_customer(customer)
            
            # Remove customer from queue
            self.queue.popleft()
            self.total_customers = len(self.queue)
            emit_state(self.env.now, "reception", "total customers num", self.total_customers)
        
        self.processing = False
    
    def notify_completion(self):
        """
        Receive notification from checkhair that a customer's full service is complete.
        """
        logger.info(f"Time {self.env.now}: Reception received completion notification from checkhair")


class CheckHair:
    """
    Hair Inspection Phase module.
    - Processing: 1 customer at a time, 7 seconds per customer
    - Coordinates between reception and cutting chair
    """
    
    def __init__(self, env: simpy.Environment, cuthair: 'CutHair', reception: Reception):
        self.env = env
        self.cuthair = cuthair
        self.reception = reception
        self.available = True
        self.current_customer: Optional[str] = None
        self.waiting_for_done = False
        
    def is_available(self) -> bool:
        """Check if the module is available to accept a new customer."""
        return self.available
    
    def receive_customer(self, customer_id: str):
        """
        Receive a customer from reception.
        
        Args:
            customer_id: Customer identifier
        """
        if not self.available:
            logger.warning(f"Time {self.env.now}: CheckHair received customer {customer_id} but not available!")
            return
        
        self.available = False
        self.current_customer = customer_id
        emit_state(self.env.now, "checkhair", "customer", "newcust")
        logger.info(f"Time {self.env.now}: CheckHair received customer {customer_id}")
        
        # Start processing
        self.env.process(self.process_customer(customer_id))
    
    def process_customer(self, customer_id: str):
        """
        Process a customer through inspection phase.
        
        Args:
            customer_id: Customer identifier
        """
        # Hold customer for 7 seconds (consultation time)
        logger.info(f"Time {self.env.now}: Inspecting customer {customer_id} for 7 seconds")
        yield self.env.timeout(7.0)
        
        # Send customer to cuthair
        logger.info(f"Time {self.env.now}: Sending customer {customer_id} to cuthair")
        emit_message(self.env.now, "checkhair", "to_cut", "newcust")
        self.cuthair.receive_customer(customer_id)
        
        # Wait for done signal from cuthair
        self.waiting_for_done = True
        logger.info(f"Time {self.env.now}: CheckHair waiting for done signal from cuthair")
        
        # The done signal will be handled by receive_done_signal
    
    def receive_done_signal(self):
        """
        Receive done signal from cuthair.
        """
        logger.info(f"Time {self.env.now}: CheckHair received done signal from cuthair")
        
        # Send notification back to reception
        logger.info(f"Time {self.env.now}: Sending completion notification to reception")
        emit_message(self.env.now, "checkhair", "to_reception", "done")
        self.reception.notify_completion()
        
        # Update state
        if self.current_customer:
            emit_state(self.env.now, "checkhair", "customer", "done")
        
        # Become available again
        self.current_customer = None
        self.available = True
        self.waiting_for_done = False
        logger.info(f"Time {self.env.now}: CheckHair is now available")


class CutHair:
    """
    Hair Cutting Phase module.
    - Processing: 1 customer at a time, 20 seconds per customer
    """
    
    def __init__(self, env: simpy.Environment, checkhair: CheckHair):
        self.env = env
        self.checkhair = checkhair
        self.total_customer_done = 0
        self.current_customer: Optional[str] = None
        
    def receive_customer(self, customer_id: str):
        """
        Receive a customer from checkhair.
        
        Args:
            customer_id: Customer identifier
        """
        self.current_customer = customer_id
        logger.info(f"Time {self.env.now}: CutHair received customer {customer_id}")
        
        # Start processing
        self.env.process(self.process_customer(customer_id))
    
    def process_customer(self, customer_id: str):
        """
        Process a customer through cutting phase.
        
        Args:
            customer_id: Customer identifier
        """
        # Hold customer for 20 seconds (cutting time)
        logger.info(f"Time {self.env.now}: Cutting customer {customer_id} hair for 20 seconds")
        yield self.env.timeout(20.0)
        
        # Signal back to checkhair that cutting is finished
        logger.info(f"Time {self.env.now}: Cutting finished for customer {customer_id}")
        emit_message(self.env.now, "cuthair", "out", "done")
        self.checkhair.receive_done_signal()
        
        # Update counter
        self.total_customer_done += 1
        emit_state(self.env.now, "cuthair", "total customer done", self.total_customer_done)
        
        self.current_customer = None


def parse_input_events():
    """
    Parse input events from stdin.
    
    Returns:
        List of (time, event_type) tuples sorted by time
    """
    events = []
    
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        
        parts = line.split()
        if len(parts) != 2:
            logger.warning(f"Skipping invalid line: {line}")
            continue
        
        time_str, event_name = parts
        
        try:
            time = parse_time(time_str)
            if event_name == "newcust":
                # Generate unique customer ID
                customer_id = f"cust_{len(events)}"
                events.append((time, customer_id))
            else:
                logger.warning(f"Skipping unknown event type: {event_name}")
        except ValueError as e:
            logger.warning(f"Skipping invalid line {line}: {e}")
    
    # Sort by time
    events.sort(key=lambda x: x[0])
    return events


def run_simulation(simulation_time: float):
    """
    Run the barbershop simulation.
    
    Args:
        simulation_time: Total simulation time in seconds
    """
    # Create SimPy environment
    env = simpy.Environment()
    
    # Create modules
    cuthair = CutHair(env, None)  # Will set checkhair reference after creation
    checkhair = CheckHair(env, cuthair, None)  # Will set reception reference after creation
    reception = Reception(env, checkhair)
    
    # Set up cross-references
    cuthair.checkhair = checkhair
    checkhair.reception = reception
    
    # Parse input events
    logger.info("Reading input events from stdin...")
    events = parse_input_events()
    logger.info(f"Read {len(events)} events")
    
    # Schedule customer arrivals
    for time, customer_id in events:
        env.process(customer_arrival(env, reception, time, customer_id))
    
    # Run simulation
    logger.info(f"Starting simulation for {simulation_time} seconds...")
    env.run(until=simulation_time)
    logger.info("Simulation completed")


def customer_arrival(env: simpy.Environment, reception: Reception, arrival_time: float, customer_id: str):
    """
    Process a customer arrival at the specified time.
    
    Args:
        env: SimPy environment
        reception: Reception module
        arrival_time: Time when customer arrives
        customer_id: Customer identifier
    """
    # Wait until arrival time
    yield env.timeout(arrival_time)
    
    # Add customer to reception
    logger.info(f"Time {env.now}: Customer {customer_id} arrived")
    reception.add_customer(customer_id)


def main():
    """Main entry point."""
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


if __name__ == "__main__":
    main()
