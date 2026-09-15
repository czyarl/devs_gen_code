#!/usr/bin/env python3
"""
Barbershop Simulation - Main Entry Point
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
    """Parse time string in HH:MM:SS:mm format to seconds"""
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
        if line:
            parts = line.split(' ', 1)
            if len(parts) == 2:
                time_str, event_name = parts
                if event_name == 'newcust':
                    time_seconds = parse_time(time_str)
                    events.append((time_seconds, event_name))
    
    # Sort events by time
    events.sort(key=lambda x: x[0])
    
    # Create simulation environment
    env = simpy.Environment()
    
    # Simulation parameters
    reception_capacity = 8
    reception_checkin_time = 5.0
    checkhair_consultation_time = 7.0
    cuthair_cutting_time = 20.0
    
    # State variables
    reception_queue = deque()
    reception_total_customers = 0
    checkhair_customer = None
    cuthair_total_customer_done = 0
    
    # Customer arrival process
    def customer_arrival(env):
        """Process customer arrivals"""
        for time_seconds, event_name in events:
            yield env.timeout(time_seconds - env.now)
            if event_name == 'newcust':
                # Process customer arrival at reception
                logging.debug(f"Customer arrives at time {env.now}")
                
                # Check if reception can accept customer
                if len(reception_queue) < reception_capacity:
                    reception_queue.append("newcust")
                    reception_total_customers += 1
                    
                    # Emit state change
                    state_event = {
                        "time": env.now,
                        "type": "state",
                        "model": "reception",
                        "field": "total customers num",
                        "value": reception_total_customers
                    }
                    print(json.dumps(state_event))
                    
                    # Process customer at reception
                    yield env.timeout(reception_checkin_time)
                    
                    # Send to checkhair
                    message_event = {
                        "time": env.now,
                        "type": "message",
                        "model": "reception",
                        "port": "cust",
                        "content": "newcust"
                    }
                    print(json.dumps(message_event))
                    
                    # Process at checkhair
                    checkhair_customer = "newcust"
                    
                    # Emit state change
                    state_event = {
                        "time": env.now,
                        "type": "state",
                        "model": "checkhair",
                        "field": "customer",
                        "value": "newcust"
                    }
                    print(json.dumps(state_event))
                    
                    yield env.timeout(checkhair_consultation_time)
                    
                    # Emit state change
                    state_event = {
                        "time": env.now,
                        "type": "state",
                        "model": "checkhair",
                        "field": "customer",
                        "value": "done"
                    }
                    print(json.dumps(state_event))
                    
                    # Send to cutting
                    message_event = {
                        "time": env.now,
                        "type": "message",
                        "model": "checkhair",
                        "port": "to_cut",
                        "content": "newcust"
                    }
                    print(json.dumps(message_event))
                    
                    # Process at cutting
                    cuthair_total_customer_done += 1
                    
                    # Emit state change
                    state_event = {
                        "time": env.now,
                        "type": "state",
                        "model": "cuthair",
                        "field": "total customer done",
                        "value": cuthair_total_customer_done
                    }
                    print(json.dumps(state_event))
                    
                    yield env.timeout(cuthair_cutting_time)
                    
                    # Send completion signal
                    message_event = {
                        "time": env.now,
                        "type": "message",
                        "model": "cuthair",
                        "port": "out",
                        "content": "done"
                    }
                    print(json.dumps(message_event))
                    
                    # Remove customer from queue
                    if len(reception_queue) > 0:
                        reception_queue.popleft()
                        reception_total_customers -= 1
                        
                        # Emit state change
                        state_event = {
                            "time": env.now,
                            "type": "state",
                            "model": "reception",
                            "field": "total customers num",
                            "value": reception_total_customers
                        }
                        print(json.dumps(state_event))
                else:
                    logging.debug(f"Customer ignored - reception queue full at time {env.now}")
    
    # Run simulation
    env.process(customer_arrival(env))
    
    # Run simulation for specified time
    env.run(until=args.simulation_time)
    
    # Print final state
    final_state = {
        "time": env.now,
        "type": "state",
        "model": "reception",
        "field": "total customers num",
        "value": reception_total_customers
    }
    print(json.dumps(final_state))

if __name__ == "__main__":
    main()