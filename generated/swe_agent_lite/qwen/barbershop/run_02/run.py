#!/usr/bin/env python3
"""
Barbershop Simulation - Main Entry Point
"""
import argparse
import sys
import json
import logging
import collections
import simpy

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)

class Reception:
    def __init__(self, env, checkhair):
        self.env = env
        self.checkhair = checkhair
        self.queue = collections.deque()
        self.capacity = 8
        self.total_customers = 0
        
    def arrive_customer(self):
        """Handle customer arrival at reception"""
        if len(self.queue) < self.capacity:
            self.queue.append("newcust")
            self.total_customers += 1
            self.log_state_change("total customers num", self.total_customers)
            self.env.process(self.process_customer())
            return True
        else:
            # Customer ignored, queue is full
            return False
    
    def process_customer(self):
        """Process customer at reception desk"""
        if self.queue:
            # Wait 5 seconds for check-in
            yield self.env.timeout(5.0)
            
            # Send customer to hair inspection
            customer = self.queue.popleft()
            self.total_customers -= 1
            self.log_state_change("total customers num", self.total_customers)
            
            # Send to checkhair
            self.checkhair.receive_customer(customer)
            self.log_message("reception", "cust", customer)
            
            # Process next customer in queue
            if self.queue:
                self.env.process(self.process_customer())
    
    def log_state_change(self, field, value):
        """Log state change to stderr"""
        event = {
            "time": self.env.now,
            "type": "state",
            "model": "reception",
            "field": field,
            "value": value
        }
        print(json.dumps(event), file=sys.stderr)
    
    def log_message(self, model, port, content):
        """Log message to stderr"""
        event = {
            "time": self.env.now,
            "type": "message",
            "model": model,
            "port": port,
            "content": content
        }
        print(json.dumps(event), file=sys.stderr)

class CheckHair:
    def __init__(self, env, cuthair):
        self.env = env
        self.cuthair = cuthair
        self.customer = None
        self.available = True
        
    def receive_customer(self, customer):
        """Receive customer from reception"""
        if self.available:
            self.customer = customer
            self.available = False
            self.log_state_change("customer", "newcust")
            self.log_message("checkhair", "to_cut", customer)
            
            # Process customer (7 seconds)
            self.env.process(self.process_customer())
        else:
            # In a real implementation, we'd need to queue this
            # For now, we'll just ignore it
            pass
    
    def process_customer(self):
        """Process customer at hair inspection"""
        # Wait 7 seconds for consultation
        yield self.env.timeout(7.0)
        
        # Send to cutting phase
        self.log_message("checkhair", "to_cut", self.customer)
        
        # Send to cutting phase
        self.cuthair.receive_customer(self.customer)
        
        # Wait for completion signal from cutting phase
        # This is handled by the cuthair module when it sends back "done"
        
    def complete_service(self):
        """Complete service and notify reception"""
        self.customer = None
        self.available = True
        self.log_state_change("customer", "done")
        self.log_message("checkhair", "to_reception", "done")
        
    def log_state_change(self, field, value):
        """Log state change to stderr"""
        event = {
            "time": self.env.now,
            "type": "state",
            "model": "checkhair",
            "field": field,
            "value": value
        }
        print(json.dumps(event), file=sys.stderr)
    
    def log_message(self, model, port, content):
        """Log message to stderr"""
        event = {
            "time": self.env.now,
            "type": "message",
            "model": model,
            "port": port,
            "content": content
        }
        print(json.dumps(event), file=sys.stderr)

class CutHair:
    def __init__(self, env, checkhair):
        self.env = env
        self.checkhair = checkhair
        self.total_customer_done = 0
        
    def receive_customer(self, customer):
        """Receive customer from checkhair"""
        # Process customer (20 seconds)
        self.env.process(self.process_customer(customer))
        
    def process_customer(self, customer):
        """Process customer at hair cutting"""
        # Wait 20 seconds for cutting
        yield self.env.timeout(20.0)
        
        # Signal completion back to checkhair
        self.total_customer_done += 1
        self.log_state_change("total customer done", self.total_customer_done)
        self.log_message("cuthair", "out", "done")
        
        # Notify checkhair that service is complete
        self.checkhair.complete_service()
        
    def log_state_change(self, field, value):
        """Log state change to stderr"""
        event = {
            "time": self.env.now,
            "type": "state",
            "model": "cuthair",
            "field": field,
            "value": value
        }
        print(json.dumps(event), file=sys.stderr)
    
    def log_message(self, model, port, content):
        """Log message to stderr"""
        event = {
            "time": self.env.now,
            "type": "message",
            "model": model,
            "port": port,
            "content": content
        }
        print(json.dumps(event), file=sys.stderr)

class BarbershopSimulation:
    def __init__(self, simulation_time=1000000.0):
        self.simulation_time = simulation_time
        self.env = simpy.Environment()
        self.checkhair = CheckHair(self.env, None)  # Will be set later
        self.cuthair = CutHair(self.env, self.checkhair)
        self.reception = Reception(self.env, self.checkhair)
        
        # Set up the connection between checkhair and cuthair
        self.checkhair.cuthair = self.cuthair
        
        # Store events for output
        self.events = []
        
    def run(self):
        # Process all input events first
        self.process_input_events()
        
        # Run simulation
        self.env.run(until=self.simulation_time)
        
        # Output all events
        for event in self.events:
            print(json.dumps(event))
    
    def process_input_events(self):
        """Process all input events from stdin"""
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
                
            try:
                # Parse the input line: HH:MM:SS:mm EventName
                parts = line.split(' ', 1)
                if len(parts) != 2:
                    logging.warning(f"Invalid input line format: {line}")
                    continue
                    
                time_str, event_name = parts
                if event_name != "newcust":
                    logging.warning(f"Unknown event type: {event_name}")
                    continue
                    
                # Convert time string to seconds
                time_parts = time_str.split(':')
                if len(time_parts) != 4:
                    logging.warning(f"Invalid time format: {time_str}")
                    continue
                    
                hours, minutes, seconds, milliseconds = map(int, time_parts)
                sim_time = hours * 3600 + minutes * 60 + seconds + milliseconds / 100
                
                # Schedule the event
                self.env.process(self.schedule_customer(sim_time))
                
            except Exception as e:
                logging.error(f"Error processing input line: {line} - {e}")
    
    def schedule_customer(self, sim_time):
        """Schedule a new customer arrival"""
        yield self.env.timeout(sim_time)
        self.reception.arrive_customer()

def main():
    parser = argparse.ArgumentParser(description='Barbershop Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0, 
                       help='Total simulation time in seconds (default: 1000000.0)')
    
    args = parser.parse_args()
    
    # Create and run simulation
    simulation = BarbershopSimulation(args.simulation_time)
    simulation.run()

if __name__ == "__main__":
    main()