#!/usr/bin/env python3
"""
Hair inspection module for barbershop simulation
"""
import simpy
import json
import sys

class CheckHair:
    def __init__(self, env, reception):
        self.env = env
        self.reception = reception
        self.customer = None  # None = available, "newcust" = processing, "done" = finished
        self.processing_time = 7.0  # 7 seconds per customer
        self.cuthair = None  # Will be set by main
        
    def receive_customer(self, customer):
        """Receive customer from reception"""
        if self.customer is None:  # Available
            self.customer = customer
            # Log state change
            state_change = {
                "time": self.env.now,
                "type": "state",
                "model": "checkhair",
                "field": "customer",
                "value": self.customer
            }
            print(json.dumps(state_change), file=sys.stdout)
            
            # Process the customer
            self.env.process(self._process_customer())
        else:
            # Queue for later processing
            pass
            
    def _process_customer(self):
        """Process customer at hair inspection"""
        if self.customer == "newcust":
            # Wait for 7 seconds
            yield self.env.timeout(self.processing_time)
            
            # Send customer to cutting phase
            # Log message
            message = {
                "time": self.env.now,
                "type": "message",
                "model": "checkhair",
                "port": "to_cut",
                "content": self.customer
            }
            print(json.dumps(message), file=sys.stdout)
            
            # Send to cutting phase
            if self.cuthair:
                self.cuthair.receive_customer(self.customer)
            
    def notify_completion(self):
        """Notify that customer service is complete"""
        if self.customer == "done":
            # Log state change
            state_change = {
                "time": self.env.now,
                "type": "state",
                "model": "checkhair",
                "field": "customer",
                "value": "available"
            }
            print(json.dumps(state_change), file=sys.stdout)
            
            # Notify reception that service is complete
            message = {
                "time": self.env.now,
                "type": "message",
                "model": "checkhair",
                "port": "to_reception",
                "content": "done"
            }
            print(json.dumps(message), file=sys.stdout)
            
            self.customer = None