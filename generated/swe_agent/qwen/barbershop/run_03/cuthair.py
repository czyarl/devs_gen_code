#!/usr/bin/env python3
"""
Hair cutting module for barbershop simulation
"""
import simpy
import json
import sys

class CutHair:
    def __init__(self, env, checkhair):
        self.env = env
        self.checkhair = checkhair
        self.customer = None  # None = available, "newcust" = processing
        self.total_customer_done = 0
        self.processing_time = 20.0  # 20 seconds per customer
        
    def receive_customer(self, customer):
        """Receive customer from hair inspection"""
        if self.customer is None:  # Available
            self.customer = customer
            # Log state change
            state_change = {
                "time": self.env.now,
                "type": "state",
                "model": "cuthair",
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
        """Process customer at hair cutting"""
        if self.customer == "newcust":
            # Wait for 20 seconds
            yield self.env.timeout(self.processing_time)
            
            # Log completion
            message = {
                "time": self.env.now,
                "type": "message",
                "model": "cuthair",
                "port": "out",
                "content": "done"
            }
            print(json.dumps(message), file=sys.stdout)
            
            # Update counter
            self.total_customer_done += 1
            # Log state change
            state_change = {
                "time": self.env.now,
                "type": "state",
                "model": "cuthair",
                "field": "total customer done",
                "value": self.total_customer_done
            }
            print(json.dumps(state_change), file=sys.stdout)
            
            # Notify checkhair that cutting is done
            self.customer = "done"
            # Notify checkhair module
            self.checkhair.notify_completion()