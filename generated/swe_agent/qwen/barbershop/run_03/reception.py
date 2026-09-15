#!/usr/bin/env python3
"""
Reception module for barbershop simulation
"""
import simpy
import json
import sys

class Reception:
    def __init__(self, env):
        self.env = env
        self.queue = []
        self.max_queue_size = 8
        self.total_customers = 0
        self.processing_time = 5.0  # 5 seconds per customer
        self.checkhair = None  # Will be set by main
        
    def arrive_customer(self):
        """Handle customer arrival at reception"""
        if len(self.queue) < self.max_queue_size:
            self.queue.append('newcust')
            self.total_customers += 1
            # Log state change
            state_change = {
                "time": self.env.now,
                "type": "state",
                "model": "reception",
                "field": "total customers num",
                "value": self.total_customers
            }
            print(json.dumps(state_change), file=sys.stdout)
            
            # Start processing if not already processing
            if len(self.queue) == 1:
                self.env.process(self._process_customer())
        else:
            # Customer ignored due to full queue
            pass
            
    def _process_customer(self):
        """Process customer at reception desk"""
        if self.queue:
            # Wait for 5 seconds
            yield self.env.timeout(self.processing_time)
            
            # Send customer to hair inspection
            customer = self.queue.pop(0)
            # Log message
            message = {
                "time": self.env.now,
                "type": "message",
                "model": "reception",
                "port": "cust",
                "content": customer
            }
            print(json.dumps(message), file=sys.stdout)
            
            # Send to checkhair
            if self.checkhair:
                self.checkhair.receive_customer(customer)
            
            # Process next customer if available
            if self.queue:
                self.env.process(self._process_customer())