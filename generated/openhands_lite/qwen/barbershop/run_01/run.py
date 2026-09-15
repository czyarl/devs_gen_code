#!/usr/bin/env python3
"""
Barbershop Simulation using Discrete Event Simulation (DES) with SimPy
"""
import argparse
import sys
import json
import logging
import simpy
from collections import deque

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BarbershopSimulation:
    def __init__(self, simulation_time=1000000.0):
        self.simulation_time = simulation_time
        self.env = simpy.Environment()
        self.reception_queue = deque()
        self.reception_capacity = 8
        self.reception_customers = 0
        self.checkhair_busy = False
        self.cuthair_busy = False
        self.total_customers_done = 0
        self.events = []
        
        # Create modules
        self.reception = ReceptionModule(self.env, self)
        self.checkhair = CheckhairModule(self.env, self)
        self.cuthair = CuthairModule(self.env, self)
        
    def add_event(self, event):
        """Add an event to the simulation"""
        self.events.append(event)
        
    def run(self):
        """Run the simulation"""
        # Process all events from stdin
        scheduled_events = []
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                # Parse the event line: HH:MM:SS:mm EventName
                parts = line.split(' ', 1)
                if len(parts) != 2:
                    continue
                time_str, event_name = parts
                if event_name != 'newcust':
                    continue
                    
                # Parse time: HH:MM:SS:mm
                time_parts = time_str.split(':')
                if len(time_parts) != 4:
                    continue
                hours, minutes, seconds, milliseconds = map(int, time_parts)
                sim_time = hours * 3600 + minutes * 60 + seconds + milliseconds / 100
                
                # Schedule the event
                scheduled_events.append((sim_time, event_name))
            except Exception as e:
                logger.warning(f"Error parsing event line '{line}': {e}")
                continue
        
        # Sort events by time
        scheduled_events.sort(key=lambda x: x[0])
        
        # Schedule all events
        for sim_time, event_name in scheduled_events:
            self.env.process(self.schedule_event(sim_time, event_name))
        
        # Run the simulation
        self.env.run(until=self.simulation_time)
        
        # Output all events
        for event in self.events:
            print(json.dumps(event))
            
    def schedule_event(self, sim_time, event_name):
        """Schedule an event at a specific simulation time"""
        yield self.env.timeout(sim_time)
        if event_name == 'newcust':
            self.reception.arrive_customer()
            
    def process_queue(self):
        """Process the reception queue"""
        if self.reception_queue and not self.checkhair_busy:
            # Send customer to checkhair
            customer = self.reception_queue.popleft()
            self.reception_customers -= 1
            
            # Log state change
            self.add_event({
                "time": self.env.now,
                "type": "state",
                "model": "reception",
                "field": "total customers num",
                "value": self.reception_customers
            })
            
            # Log message
            self.add_event({
                "time": self.env.now,
                "type": "message",
                "model": "reception",
                "port": "cust",
                "content": "newcust"
            })
            
            # Send to checkhair
            self.checkhair.receive_customer()

class ReceptionModule:
    def __init__(self, env, simulation):
        self.env = env
        self.simulation = simulation
        self.name = "reception"
        
    def arrive_customer(self):
        """Handle customer arrival at reception"""
        # Check if queue has space
        if len(self.simulation.reception_queue) < self.simulation.reception_capacity:
            # Add customer to queue
            self.simulation.reception_queue.append(self.env.now)
            self.simulation.reception_customers += 1
            
            # Log state change
            self.simulation.add_event({
                "time": self.env.now,
                "type": "state",
                "model": self.name,
                "field": "total customers num",
                "value": self.simulation.reception_customers
            })
            
            # Process the customer (5 seconds)
            self.env.process(self.process_customer())
        else:
            # Queue is full, ignore customer
            logger.info(f"Reception queue full at {self.env.now}, ignoring new customer")
            
    def process_customer(self):
        """Process customer at reception (5 seconds)"""
        # Wait for 5 seconds
        yield self.env.timeout(5.0)
        
        # Process the queue
        self.simulation.process_queue()

class CheckhairModule:
    def __init__(self, env, simulation):
        self.env = env
        self.simulation = simulation
        self.name = "checkhair"
        
    def receive_customer(self):
        """Receive customer from reception"""
        self.simulation.checkhair_busy = True
        
        # Log state change
        self.simulation.add_event({
            "time": self.env.now,
            "type": "state",
            "model": self.name,
            "field": "customer",
            "value": "newcust"
        })
        
        # Process customer (7 seconds)
        self.env.process(self.process_customer())
        
    def process_customer(self):
        """Process customer at checkhair (7 seconds)"""
        # Wait for 7 seconds
        yield self.env.timeout(7.0)
        
        # Send customer to cuthair
        self.simulation.add_event({
            "time": self.env.now,
            "type": "message",
            "model": self.name,
            "port": "to_cut",
            "content": "newcust"
        })
        
        # Send to cuthair
        self.simulation.cuthair.receive_customer()
        
    def notify_completion(self):
        """Notify that customer is done at checkhair"""
        self.simulation.checkhair_busy = False
        
        # Log state change
        self.simulation.add_event({
            "time": self.env.now,
            "type": "state",
            "model": self.name,
            "field": "customer",
            "value": "done"
        })
        
        # Log message
        self.simulation.add_event({
            "time": self.env.now,
            "type": "message",
            "model": self.name,
            "port": "to_reception",
            "content": "done"
        })

class CuthairModule:
    def __init__(self, env, simulation):
        self.env = env
        self.simulation = simulation
        self.name = "cuthair"
        
    def receive_customer(self):
        """Receive customer from checkhair"""
        self.simulation.cuthair_busy = True
        
        # Log state change
        self.simulation.add_event({
            "time": self.env.now,
            "type": "state",
            "model": self.name,
            "field": "customer",
            "value": "newcust"
        })
        
        # Process customer (20 seconds)
        self.env.process(self.process_customer())
        
    def process_customer(self):
        """Process customer at cuthair (20 seconds)"""
        # Wait for 20 seconds
        yield self.env.timeout(20.0)
        
        # Log message
        self.simulation.add_event({
            "time": self.env.now,
            "type": "message",
            "model": self.name,
            "port": "out",
            "content": "done"
        })
        
        # Update total customers done
        self.simulation.total_customers_done += 1
        
        # Log state change
        self.simulation.add_event({
            "time": self.env.now,
            "type": "state",
            "model": self.name,
            "field": "total customer done",
            "value": self.simulation.total_customers_done
        })
        
        # Notify checkhair of completion
        self.simulation.checkhair.notify_completion()
        
        # Reset cuthair busy flag
        self.simulation.cuthair_busy = False

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