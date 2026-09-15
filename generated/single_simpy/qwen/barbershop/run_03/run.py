import argparse
import sys
import json
import logging
from collections import deque
import simpy

# Define the simulation environment
class BarbershopSimulation:
    def __init__(self, simulation_time=1000000.0):
        self.env = simpy.Environment()
        self.simulation_time = simulation_time
        
        # Modules
        self.reception = ReceptionModule(self.env, self)
        self.checkhair = CheckHairModule(self.env, self)
        self.cuthair = CutHairModule(self.env, self)
        
        # Schedule events
        self.events = []
        
    def run(self):
        # Process all events from stdin
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                time_str, event_name = line.split(' ', 1)
                if event_name != "newcust":
                    continue
                # Parse time string: HH:MM:SS:mm
                h, m, s, ms = map(int, time_str.split(':'))
                sim_time = h * 3600 + m * 60 + s + ms / 100.0
                self.events.append((sim_time, event_name))
            except Exception as e:
                print(f"Error parsing line: {line} - {e}", file=sys.stderr)
        
        # Sort events by time
        self.events.sort()
        
        # Schedule all events
        for time, event_name in self.events:
            self.env.process(self.schedule_event(time, event_name))
        
        # Start simulation
        self.env.run(until=self.simulation_time)
        
        # Print final state
        self.print_final_state()
    
    def schedule_event(self, time, event_name):
        if event_name == "newcust":
            yield self.env.timeout(time - self.env.now)
            self.reception.arrive_customer()
    
    def print_final_state(self):
        # Print final state of all modules
        print(json.dumps({
            "time": self.env.now,
            "type": "state",
            "model": "reception",
            "field": "total customers",
            "value": self.reception.customer_count
        }), file=sys.stdout)
        
        print(json.dumps({
            "time": self.env.now,
            "type": "state",
            "model": "checkhair",
            "field": "customer",
            "value": self.checkhair.customer
        }), file=sys.stdout)
        
        print(json.dumps({
            "time": self.env.now,
            "type": "state",
            "model": "cuthair",
            "field": "total customer done",
            "value": self.cuthair.total_done
        }), file=sys.stdout)

# Reception Module
class ReceptionModule:
    def __init__(self, env, simulation):
        self.env = env
        self.simulation = simulation
        self.queue = deque()
        self.customer_count = 0
        self.capacity = 8
        
        # Start the processing loop
        self.env.process(self.process_queue())
        
    def arrive_customer(self):
        if self.customer_count < self.capacity:
            self.queue.append(self.env.now)
            self.customer_count += 1
            print(json.dumps({
                "time": self.env.now,
                "type": "state",
                "model": "reception",
                "field": "total customers",
                "value": self.customer_count
            }), file=sys.stdout)
            
            # Send message to checkhair
            print(json.dumps({
                "time": self.env.now,
                "type": "message",
                "model": "reception",
                "port": "cust",
                "content": "newcust"
            }), file=sys.stdout)
            
            # Notify checkhair that we have a customer
            self.simulation.checkhair.receive_customer()
        else:
            # Customer ignored
            pass
    
    def process_queue(self):
        while True:
            if self.queue:
                # Process the first customer in queue
                yield self.env.timeout(5.0)  # Processing time
                # Remove the customer from queue
                self.queue.popleft()
                self.customer_count -= 1
                print(json.dumps({
                    "time": self.env.now,
                    "type": "state",
                    "model": "reception",
                    "field": "total customers",
                    "value": self.customer_count
                }), file=sys.stdout)
                
                # Send to checkhair if available
                if not self.simulation.checkhair.is_busy():
                    self.simulation.checkhair.receive_customer()
            else:
                yield self.env.timeout(1.0)  # Wait for next customer

# Check Hair Module
class CheckHairModule:
    def __init__(self, env, simulation):
        self.env = env
        self.simulation = simulation
        self.customer = "none"  # "none", "newcust", "done"
        self.is_busy_flag = False
        
    def is_busy(self):
        return self.is_busy_flag
    
    def receive_customer(self):
        if not self.is_busy_flag:
            self.customer = "newcust"
            self.is_busy_flag = True
            print(json.dumps({
                "time": self.env.now,
                "type": "state",
                "model": "checkhair",
                "field": "customer",
                "value": self.customer
            }), file=sys.stdout)
            
            # Process for 7 seconds
            yield self.env.timeout(7.0)
            
            # Send to cutting phase
            print(json.dumps({
                "time": self.env.now,
                "type": "message",
                "model": "checkhair",
                "port": "to_cut",
                "content": "newcust"
            }), file=sys.stdout)
            
            # Notify cuthair
            self.simulation.cuthair.receive_customer()
            
            # Wait for completion signal
            yield self.env.timeout(1.0)  # Wait for completion signal
            
            # Send to reception that customer is done
            print(json.dumps({
                "time": self.env.now,
                "type": "message",
                "model": "checkhair",
                "port": "to_reception",
                "content": "done"
            }), file=sys.stdout)
            
            # Notify reception that service is done
            self.simulation.reception.customer_done()
            
            # Reset state
            self.customer = "done"
            self.is_busy_flag = False
            print(json.dumps({
                "time": self.env.now,
                "type": "state",
                "model": "checkhair",
                "field": "customer",
                "value": self.customer
            }), file=sys.stdout)
    
    def customer_done(self):
        pass  # This is just a notification

# Cut Hair Module
class CutHairModule:
    def __init__(self, env, simulation):
        self.env = env
        self.simulation = simulation
        self.total_done = 0
        
    def receive_customer(self):
        # Process for 20 seconds
        yield self.env.timeout(20.0)
        
        # Signal completion
        self.total_done += 1
        print(json.dumps({
            "time": self.env.now,
            "type": "state",
            "model": "cuthair",
            "field": "total customer done",
            "value": self.total_done
        }), file=sys.stdout)
        
        print(json.dumps({
            "time": self.env.now,
            "type": "message",
            "model": "cuthair",
            "port": "out",
            "content": "done"
        }), file=sys.stdout)
        
        # Notify checkhair that we're done
        self.simulation.checkhair.customer_done()

# Main function
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--simulation_time', type=float, default=1000000.0)
    args = parser.parse_args()
    
    # Create and run simulation
    sim = BarbershopSimulation(simulation_time=args.simulation_time)
    sim.run()

if __name__ == "__main__":
    main()