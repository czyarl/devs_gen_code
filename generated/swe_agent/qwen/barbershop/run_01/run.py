#!/usr/bin/env python3
"""
Barbershop Simulation - Main Entry Point
"""
import argparse
import sys
import json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stderr)

def parse_time(time_str):
    """Parse time string HH:MM:SS:mm into seconds"""
    h, m, s, ms = map(int, time_str.split(':'))
    return h * 3600 + m * 60 + s + ms / 100.0

def main():
    # Parse command line arguments
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
            time_sec = parse_time(time_str)
            events.append((time_sec, event_name))
        except ValueError:
            logging.warning(f"Invalid input line: {line}")
    
    # Sort events by time
    events.sort(key=lambda x: x[0])
    
    # Initialize state variables
    reception_customers = 0
    checkhair_status = "available"
    cuthair_done = 0
    
    # Process events
    for time_sec, event_name in events:
        if event_name == "newcust":
            # Reception desk logic
            if reception_customers < 8:
                reception_customers += 1
                
                # Log state change
                print(json.dumps({
                    "time": time_sec,
                    "type": "state",
                    "model": "reception",
                    "field": "total customers",
                    "value": reception_customers
                }), file=sys.stdout)
                
                # Simulate 5 seconds processing time
                processing_time = time_sec + 5
                
                # Log message
                print(json.dumps({
                    "time": processing_time,
                    "type": "message",
                    "model": "reception",
                    "port": "cust",
                    "content": "newcust"
                }), file=sys.stdout)
                
                # Simulate checkhair processing (7 seconds)
                checkhair_time = processing_time + 7
                
                # Log state change for checkhair
                print(json.dumps({
                    "time": checkhair_time,
                    "type": "state",
                    "model": "checkhair",
                    "field": "customer",
                    "value": "newcust"
                }), file=sys.stdout)
                
                # Log message to cuthair
                print(json.dumps({
                    "time": checkhair_time,
                    "type": "message",
                    "model": "checkhair",
                    "port": "to_cut",
                    "content": "newcust"
                }), file=sys.stdout)
                
                # Simulate cuthair processing (20 seconds)
                cuthair_time = checkhair_time + 20
                
                # Log state change for cuthair
                print(json.dumps({
                    "time": cuthair_time,
                    "type": "state",
                    "model": "cuthair",
                    "field": "total customer done",
                    "value": cuthair_done + 1
                }), file=sys.stdout)
                
                # Log completion message
                print(json.dumps({
                    "time": cuthair_time,
                    "type": "message",
                    "model": "cuthair",
                    "port": "out",
                    "content": "done"
                }), file=sys.stdout)
                
                # Log completion back to reception
                print(json.dumps({
                    "time": cuthair_time,
                    "type": "message",
                    "model": "checkhair",
                    "port": "to_reception",
                    "content": "done"
                }), file=sys.stdout)
                
                # Log state change for checkhair
                print(json.dumps({
                    "time": cuthair_time,
                    "type": "state",
                    "model": "checkhair",
                    "field": "customer",
                    "value": "available"
                }), file=sys.stdout)
                
                # Update done counter
                cuthair_done += 1
                
                # Log state change for reception
                reception_customers -= 1
                print(json.dumps({
                    "time": cuthair_time,
                    "type": "state",
                    "model": "reception",
                    "field": "total customers",
                    "value": reception_customers
                }), file=sys.stdout)
            else:
                # Customer ignored - no state change needed
                # In a real implementation, we would not log anything for ignored customers
                pass
    
    # Print final state
    print(json.dumps({"time": args.simulation_time, "type": "state", "model": "reception", "field": "total customers", "value": reception_customers}))
    print(json.dumps({"time": args.simulation_time, "type": "state", "model": "checkhair", "field": "customer", "value": checkhair_status}))
    print(json.dumps({"time": args.simulation_time, "type": "state", "model": "cuthair", "field": "total customer done", "value": cuthair_done}))

if __name__ == "__main__":
    main()