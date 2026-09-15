#!/usr/bin/env python3
"""
Barbershop Simulation System
"""

import argparse
import sys
import json
import logging
from collections import deque
import simpy

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)

def parse_time(time_str):
    """Parse time string HH:MM:SS:mm to seconds"""
    h, m, s, ms = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s + ms / 100.0

def main():
    parser = argparse.ArgumentParser(description='Barbershop Simulation')
    parser.add_argument('--simulation_time', type=float, default=1000000.0, 
                       help='Total simulation time in seconds (default: 1000000.0)')
    
    args = parser.parse_args()
    
    # Read input from stdin
    events = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            time_str, event_name = line.split(' ', 1)
            if event_name == 'newcust':
                time = parse_time(time_str)
                events.append((time, event_name))
        except ValueError:
            logging.warning(f"Invalid input line: {line}")
    
    # Sort events by time
    events.sort(key=lambda x: x[0])
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Simulation state variables
    reception_queue = deque()
    reception_customers = 0
    checkhair_busy = False
    cuthair_busy = False
    total_customer_done = 0
    reception_capacity = 8
    checkin_time = 5.0
    consultation_time = 7.0
    cutting_time = 20.0
    
    def emit_state_change(model, field, value):
        """Emit a state change message"""
        message = {
            "time": env.now,
            "type": "state",
            "model": model,
            "field": field,
            "value": value
        }
        print(json.dumps(message))
    
    def emit_message(model, port, content):
        """Emit a message"""
        message = {
            "time": env.now,
            "type": "message",
            "model": model,
            "port": port,
            "content": content
        }
        print(json.dumps(message))
    
    def customer_arrival(time):
        """Handle customer arrival at a specific time"""
        # Wait until the scheduled time
        yield env.timeout(time)
        
        # Check if queue has space
        if len(reception_queue) < reception_capacity:
            reception_queue.append("newcust")
            nonlocal reception_customers
            reception_customers += 1
            emit_state_change("reception", "total customers num", reception_customers)
            
            # Process the customer (5 seconds)
            yield env.timeout(checkin_time)
            
            # Remove from queue
            reception_queue.popleft()
            reception_customers -= 1
            emit_state_change("reception", "total customers num", reception_customers)
            
            # Send to checkhair
            emit_message("reception", "cust", "newcust")
            
            # Signal to checkhair that a customer is ready
            if not checkhair_busy:
                nonlocal checkhair_busy
                checkhair_busy = True
                env.process(hair_inspection())
        else:
            # Customer ignored due to full queue
            pass
    
    def hair_inspection():
        """Hair inspection process"""
        nonlocal checkhair_busy, cuthair_busy
        
        if len(reception_queue) > 0 and not checkhair_busy:
            # Get customer from queue
            customer = reception_queue.popleft()
            nonlocal reception_customers
            reception_customers -= 1
            emit_state_change("reception", "total customers num", reception_customers)
            
            checkhair_busy = True
            emit_state_change("checkhair", "customer", "newcust")
            
            # Process customer (7 seconds)
            yield env.timeout(consultation_time)
            
            # Send to cutting
            emit_message("checkhair", "to_cut", "newcust")
            emit_state_change("checkhair", "customer", "done")
            
            # Signal to cutting process
            if not cuthair_busy:
                nonlocal cuthair_busy
                cuthair_busy = True
                env.process(hair_cutting())
    
    def hair_cutting():
        """Hair cutting process"""
        nonlocal cuthair_busy
        
        cuthair_busy = True
        emit_state_change("cuthair", "customer", "newcust")
        
        # Process customer (20 seconds)
        yield env.timeout(cutting_time)
        
        nonlocal total_customer_done
        total_customer_done += 1
        cuthair_busy = False
        emit_state_change("cuthair", "total customer done", total_customer_done)
        emit_message("cuthair", "out", "done")
        
        # Signal back to checkhair that cutting is done
        nonlocal checkhair_busy
        checkhair_busy = False
        emit_message("checkhair", "to_reception", "done")
    
    # Process all events
    for time, event_name in events:
        if event_name == 'newcust':
            env.process(customer_arrival(time))
    
    # Run simulation
    try:
        env.run(until=args.simulation_time)
    except Exception as e:
        logging.error(f"Simulation error: {e}")

if __name__ == "__main__":
    main()