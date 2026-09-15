#!/usr/bin/env python3
"""
Barbershop Simulation - Module Definitions
"""
import simpy
import json
import sys

class Reception:
    def __init__(self, env, name, checkhair_store, max_queue=8):
        self.env = env
        self.name = name
        self.total_customers = 0
        self.max_queue = max_queue
        self.checkhair_store = checkhair_store
        
    def arrive_customer(self, arrival_time):
        """Handle customer arrival"""
        # Check if queue has space
        if self.total_customers < self.max_queue:
            self.total_customers += 1
            
            # Log state change
            print(json.dumps({
                "time": self.env.now,
                "type": "state",
                "model": self.name,
                "field": "total customers",
                "value": self.total_customers
            }), file=sys.stdout)
            
            # Process customer (5 seconds)
            yield self.env.timeout(5)
            
            # Remove from queue and send to checkhair
            self.total_customers -= 1
            
            # Log message
            print(json.dumps({
                "time": self.env.now,
                "type": "message",
                "model": self.name,
                "port": "cust",
                "content": "newcust"
            }), file=sys.stdout)
            
            # Send to checkhair
            self.checkhair_store.put("newcust")
            
            # Log state change after processing
            print(json.dumps({
                "time": self.env.now,
                "type": "state",
                "model": self.name,
                "field": "total customers",
                "value": self.total_customers
            }), file=sys.stdout)
        else:
            # Customer ignored - no state change needed
            pass

class CheckHair:
    def __init__(self, env, name, cuthair_store):
        self.env = env
        self.name = name
        self.customer_status = "available"  # "available", "newcust", "done"
        self.cuthair_store = cuthair_store
        
    def process_customer(self):
        """Process customer at checkhair"""
        # Wait for customer from reception
        customer = yield self.cuthair_store.get()
        
        # Update status
        self.customer_status = "newcust"
        
        # Log state change
        print(json.dumps({
            "time": self.env.now,
            "type": "state",
            "model": self.name,
            "field": "customer",
            "value": self.customer_status
        }), file=sys.stdout)
        
        # Process for 7 seconds
        yield self.env.timeout(7)
        
        # Update status
        self.customer_status = "done"
        
        # Log state change
        print(json.dumps({
            "time": self.env.now,
            "type": "state",
            "model": self.name,
            "field": "customer",
            "value": self.customer_status
        }), file=sys.stdout)
        
        # Send to cuthair
        print(json.dumps({
            "time": self.env.now,
            "type": "message",
            "model": self.name,
            "port": "to_cut",
            "content": "newcust"
        }), file=sys.stdout)
        
        self.cuthair_store.put("newcust")
        
        # Wait for completion signal from cuthair
        completion = yield self.cuthair_store.get()
        
        # Log completion
        print(json.dumps({
            "time": self.env.now,
            "type": "message",
            "model": self.name,
            "port": "to_reception",
            "content": "done"
        }), file=sys.stdout)
        
        # Update status back to available
        self.customer_status = "available"
        
        # Log state change
        print(json.dumps({
            "time": self.env.now,
            "type": "state",
            "model": self.name,
            "field": "customer",
            "value": self.customer_status
        }), file=sys.stdout)

class CutHair:
    def __init__(self, env, name, checkhair_store):
        self.env = env
        self.name = name
        self.total_done = 0
        self.checkhair_store = checkhair_store
        
    def process_customer(self):
        """Process customer at cut hair"""
        # Wait for customer from checkhair
        customer = yield self.checkhair_store.get()
        
        # Process for 20 seconds
        yield self.env.timeout(20)
        
        # Increment done counter
        self.total_done += 1
        
        # Log state change
        print(json.dumps({
            "time": self.env.now,
            "type": "state",
            "model": self.name,
            "field": "total customer done",
            "value": self.total_done
        }), file=sys.stdout)
        
        # Send completion signal back to checkhair
        print(json.dumps({
            "time": self.env.now,
            "type": "message",
            "model": self.name,
            "port": "out",
            "content": "done"
        }), file=sys.stdout)
        
        self.checkhair_store.put("done")