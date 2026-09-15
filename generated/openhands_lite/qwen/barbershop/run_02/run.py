#!/usr/bin/env python3
"""
Barbershop Simulation using Discrete Event Simulation (DES) with SimPy
"""

import argparse
import sys
import json
import logging
import simpy


# Configure logging to stderr
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)


class ReceptionDesk:
    """Reception desk module for barbershop simulation"""
    
    def __init__(self, env, checkhair_module):
        self.env = env
        self.checkhair_module = checkhair_module
        self.queue = []
        self.total_customers = 0
        self.capacity = 8
        self.processing_time = 5.0  # seconds
        
    def receive_customer(self, customer):
        """Receive a new customer"""
        if len(self.queue) < self.capacity:
            self.queue.append(customer)
            self.total_customers += 1
            logger.debug(f"Reception: Customer {customer} added to queue. Queue size: {len(self.queue)}")
            
            # Emit state change
            state_event = {
                "time": self.env.now,
                "type": "state",
                "model": "reception",
                "field": "total customers num",
                "value": self.total_customers
            }
            print(json.dumps(state_event))
            
            # Emit message
            message_event = {
                "time": self.env.now,
                "type": "message",
                "model": "reception",
                "port": "cust",
                "content": "newcust"
            }
            print(json.dumps(message_event))
            
            # Process the queue
            self.env.process(self._process_queue())
            return True
        else:
            logger.debug(f"Reception: Queue full, customer {customer} rejected")
            return False
    
    def _process_queue(self):
        """Process customers in the queue"""
        # Wait for 5 seconds (check-in time)
        yield self.env.timeout(self.processing_time)
        
        # Check if checkhair is available
        if self.checkhair_module.is_available():
            # Send customer to checkhair
            customer = self.queue.pop(0)  # Remove processed customer from queue
            self.total_customers -= 1
            logger.debug(f"Reception: Sending customer {customer} to checkhair at time {self.env.now}")
            
            # Emit state change for queue size
            state_event = {
                "time": self.env.now,
                "type": "state",
                "model": "reception",
                "field": "total customers num",
                "value": self.total_customers
            }
            print(json.dumps(state_event))
            
            self.checkhair_module.receive_customer(customer)
        else:
            # If checkhair is not available, wait and try again
            logger.debug(f"Reception: Checkhair busy, waiting for availability at time {self.env.now}")
            # Re-schedule the processing
            self.env.process(self._process_queue())


class CheckHairModule:
    """Hair inspection phase module"""
    
    def __init__(self, env, cuthair_module):
        self.env = env
        self.cuthair_module = cuthair_module
        self.customer = None  # Current customer being inspected
        self.processing_time = 7.0  # seconds
        self.available = True
        
    def is_available(self):
        """Check if the module is available"""
        return self.available
        
    def receive_customer(self, customer):
        """Receive customer from reception"""
        if self.available:
            self.customer = customer
            self.available = False
            
            logger.debug(f"CheckHair: Starting inspection of customer {customer} at time {self.env.now}")
            
            # Emit state change
            state_event = {
                "time": self.env.now,
                "type": "state",
                "model": "checkhair",
                "field": "customer",
                "value": "newcust"
            }
            print(json.dumps(state_event))
            
            # Start processing
            self.env.process(self._process_customer())
        else:
            logger.debug(f"CheckHair: Module busy, customer {customer} will wait")
            
    def _process_customer(self):
        """Process the customer for inspection time"""
        # Wait for 7 seconds (inspection time)
        yield self.env.timeout(self.processing_time)
        
        logger.debug(f"CheckHair: Inspection complete for customer {self.customer} at time {self.env.now}")
        
        # Send customer to cutting phase
        logger.debug(f"CheckHair: Sending customer {self.customer} to cuthair at time {self.env.now}")
        self.cuthair_module.receive_customer(self.customer)
        
        # Emit message
        message_event = {
            "time": self.env.now,
            "type": "message",
            "model": "checkhair",
            "port": "to_cut",
            "content": "newcust"
        }
        print(json.dumps(message_event))
        
        # Mark as available for next customer
        self.customer = None
        self.available = True
        
        # Emit state change
        state_event = {
            "time": self.env.now,
            "type": "state",
            "model": "checkhair",
            "field": "customer",
            "value": "done"
        }
        print(json.dumps(state_event))


class CutHairModule:
    """Hair cutting phase module"""
    
    def __init__(self, env):
        self.env = env
        self.customer = None  # Current customer being cut
        self.processing_time = 20.0  # seconds
        self.total_customer_done = 0
        
    def receive_customer(self, customer):
        """Receive customer from checkhair"""
        if self.customer is None:
            self.customer = customer
            
            logger.debug(f"CutHair: Starting cut for customer {customer} at time {self.env.now}")
            
            # Start processing
            self.env.process(self._process_customer())
        else:
            logger.debug(f"CutHair: Module busy, customer {customer} will wait")
            
    def _process_customer(self):
        """Process the customer for cutting time"""
        # Wait for 20 seconds (cutting time)
        yield self.env.timeout(self.processing_time)
        
        logger.debug(f"CutHair: Cut complete for customer {self.customer} at time {self.env.now}")
        
        # Update counter
        self.total_customer_done += 1
        
        # Emit state change
        state_event = {
            "time": self.env.now,
            "type": "state",
            "model": "cuthair",
            "field": "total customer done",
            "value": self.total_customer_done
        }
        print(json.dumps(state_event))
        
        # Signal completion back to checkhair
        logger.debug(f"CutHair: Signaling completion to checkhair for customer {self.customer} at time {self.env.now}")
        
        # Emit message
        message_event = {
            "time": self.env.now,
            "type": "message",
            "model": "cuthair",
            "port": "out",
            "content": "done"
        }
        print(json.dumps(message_event))
        
        # Clear customer
        self.customer = None


def parse_time(time_str):
    """Parse time string in format HH:MM:SS:ms to seconds"""
    try:
        h, m, s, ms = map(int, time_str.split(':'))
        return h * 3600 + m * 60 + s + ms / 100.0
    except ValueError:
        raise ValueError(f"Invalid time format: {time_str}")


def main():
    parser = argparse.ArgumentParser(description='Barbershop Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0, 
                       help='Total simulation time in seconds (default: 1000000.0)')
    
    args = parser.parse_args()
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Create modules
    cuthair_module = CutHairModule(env)
    checkhair_module = CheckHairModule(env, cuthair_module)
    reception_module = ReceptionDesk(env, checkhair_module)
    
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
            else:
                logger.warning(f"Unknown event type: {event_name}")
        except ValueError as e:
            logger.warning(f"Invalid line format: {line} - {e}")
    
    # Sort events by time
    events.sort(key=lambda x: x[0])
    
    # Schedule events at their specific times
    # In simpy, we schedule events to happen at specific times by calculating the delay from current time
    for time_seconds, event_name in events:
        if time_seconds <= args.simulation_time:
            # Schedule the event to happen at the specified time
            # We use a generator that yields a timeout for the delay
            def schedule_event(delay_time, customer_type):
                yield env.timeout(delay_time)
                reception_module.receive_customer(customer_type)
            
            # Schedule the event at the specified time (relative to simulation start)
            env.process(schedule_event(time_seconds, event_name))
    
    # Run simulation
    logger.info(f"Starting simulation with time limit {args.simulation_time} seconds")
    env.run(until=args.simulation_time)
    
    logger.info("Simulation completed")


if __name__ == "__main__":
    main()