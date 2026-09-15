import argparse
import json
import sys
import random
import math
import simpy
import numpy as np

def parse_time(time_str):
    """
    Parses a time string in HH:MM:SS:mmm format to seconds.
    """
    parts = time_str.split(':')
    if len(parts) != 4:
        raise ValueError(f"Invalid time format: {time_str}")
    
    hours, minutes, seconds, millis = map(int, parts)
    total_seconds = hours * 3600 + minutes * 60 + seconds + millis / 1000.0
    return total_seconds

def format_time(seconds):
    """
    Formats seconds (float) to HH:MM:SS:mmm string.
    """
    if seconds < 0:
        seconds = 0
        
    # Extract components
    hours = int(seconds // 3600)
    remainder = seconds % 3600
    minutes = int(remainder // 60)
    remainder = remainder % 60
    secs = int(remainder // 1)
    millis = int(round((remainder % 1) * 1000))
    
    # Handle rollover due to rounding
    if millis == 1000:
        millis = 0
        secs += 1
    if secs == 60:
        secs = 0
        minutes += 1
    if minutes == 60:
        minutes = 0
        hours += 1
        
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{millis:03d}"

class StoreSimulation:
    def __init__(self, args):
        self.env = simpy.Environment()
        self.sim_time_limit = parse_time(args.simulation_time)
        
        # Parameters
        self.client_mean = args.client_mean
        self.client_stddev = args.client_stddev
        self.emp1_mean = args.employee_1_mean
        self.emp1_stddev = args.employee_1_stddev
        self.emp2_mean = args.employee_2_mean
        self.emp2_stddev = args.employee_2_stddev
        
        # Seeding
        if args.seed is not None:
            np.random.seed(args.seed)
            random.seed(args.seed)

        # State
        self.client_counter = 1
        self.queue = [] # List of waiting client dicts: {'id': int, 'arrival_time': float}
        
        # Employee state
        # We use a dictionary to track availability and parameters
        self.employees = {
            1: {
                'mean': self.emp1_mean, 
                'stddev': self.emp1_stddev, 
                'busy': False,
                'name': "Employee_1"
            },
            2: {
                'mean': self.emp2_mean, 
                'stddev': self.emp2_stddev, 
                'busy': False,
                'name': "Employee_2"
            }
        }
        
        # Events to wake up employees when a client is assigned
        self.emp_events = {
            1: self.env.event(),
            2: self.env.event()
        }
        
        # Start processes
        self.env.process(self.client_generator_process())
        self.env.process(self.employee_process(1))
        self.env.process(self.employee_process(2))
        
        # Emit initial availability events at t=0.0
        self.emit_event(0.0, "employee_available", "employee", "Employee_1", {"employee_id": 1})
        self.emit_event(0.0, "employee_available", "employee", "Employee_2", {"employee_id": 2})

    def emit_event(self, time, event_type, entity_type, entity, payload):
        """
        Prints a JSONL event to stdout if within simulation horizon.
        """
        # Events strictly after the horizon should not be emitted.
        # If time == horizon, it is emitted.
        if time > self.sim_time_limit:
            return
            
        obj = {
            "time": round(time, 3),
            "time_str": format_time(time),
            "event": event_type,
            "entity_type": entity_type,
            "entity": entity,
            "payload": payload
        }
        print(json.dumps(obj), flush=True)

    def get_service_duration(self, emp_id):
        """
        Calculates service duration based on employee parameters.
        Clamped to [mean - 3*stddev, mean + 3*stddev].
        """
        emp = self.employees[emp_id]
        mean = emp['mean']
        stddev = emp['stddev']
        
        if stddev == 0:
            return mean
        
        val = np.random.normal(mean, stddev)
        lower = mean - 3 * stddev
        upper = mean + 3 * stddev
        duration = max(lower, min(val, upper))
        return duration

    def get_inter_arrival(self):
        """
        Calculates inter-arrival time.
        Clamped to [0, mean + 5*stddev].
        """
        mean = self.client_mean
        stddev = self.client_stddev
        
        val = np.random.normal(mean, stddev)
        upper = mean + 5 * stddev
        lower = 0
        interval = max(lower, min(val, upper))
        return interval

    def try_pair(self):
        """
        Checks for available employees and waiting clients.
        Pairs them if both exist.
        """
        # Find available employees
        available_emp_ids = [eid for eid, data in self.employees.items() if not data['busy']]
        
        if self.queue and available_emp_ids:
            # FIFO: take first client
            client = self.queue.pop(0)
            # Take first available employee
            emp_id = available_emp_ids[0]
            
            # Mark employee as busy
            self.employees[emp_id]['busy'] = True
            
            # Emit client_paired event
            self.emit_event(self.env.now, "client_paired", "queue", "Queue", {
                "client_id": client['id'],
                "employee_id": emp_id,
                "paired_time": self.env.now
            })
            
            # Trigger the employee's event to wake them up
            # Pass the client data through the event
            self.emp_events[emp_id].succeed(client)
            # Reset the event for the next wait
            self.emp_events[emp_id] = self.env.event()

    def client_generator_process(self):
        """
        Generates clients at intervals.
        """
        while True:
            current_time = self.env.now
            
            # Stop generating if we are past the horizon
            # (Though simpy.run(until) handles execution stopping, 
            # we shouldn't schedule events that effectively start past horizon)
            if current_time > self.sim_time_limit:
                break
            
            # Generate client
            client_id = self.client_counter
            self.client_counter += 1
            
            self.emit_event(current_time, "client_generated", "client_generator", "ClientGenerator", {
                "client_id": client_id,
                "arrival_time": current_time
            })
            
            client = {'id': client_id, 'arrival_time': current_time}
            self.queue.append(client)
            
            # Attempt to pair immediately
            self.try_pair()
            
            # Schedule next generation
            interval = self.get_inter_arrival()
            yield self.env.timeout(interval)

    def employee_process(self, emp_id):
        """
        Employee process: waits for client, serves, repeats.
        """
        while True:
            # Wait for a pairing event (triggered by try_pair)
            # The event returns the client object
            client = yield self.emp_events[emp_id]
            
            # Calculate service duration
            duration = self.get_service_duration(emp_id)
            
            # Simulate service
            yield self.env.timeout(duration)
            
            finish_time = self.env.now
            
            # Check horizon before emitting completion events
            if finish_time <= self.sim_time_limit:
                # Emit client_served
                delay = finish_time - client['arrival_time']
                self.emit_event(finish_time, "client_served", "employee", f"Employee_{emp_id}", {
                    "client_id": client['id'],
                    "employee_id": emp_id,
                    "arrived": client['arrival_time'],
                    "dispatched": finish_time,
                    "delay": delay
                })
                
                # Mark as available
                self.employees[emp_id]['busy'] = False
                
                # Emit employee_available
                self.emit_event(finish_time, "employee_available", "employee", f"Employee_{emp_id}", {
                    "employee_id": emp_id
                })
                
                # Try to pair with next client in queue
                self.try_pair()
            else:
                # If service finished after horizon, we don't emit events.
                # We also don't loop back to try and find more work.
                # The simulation environment will stop shortly.
                break

    def run(self):
        # Run simulation until the time limit
        self.env.run(until=self.sim_time_limit)

def main():
    parser = argparse.ArgumentParser(description="Two-Employee Store Cashier Simulation")
    
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000",
                        help="Total simulation horizon in HH:MM:SS:mmm format")
    parser.add_argument("--client_mean", type=float, default=10.0,
                        help="Mean inter-arrival time for clients")
    parser.add_argument("--client_stddev", type=float, default=5.0,
                        help="Standard deviation for inter-arrival time")
    parser.add_argument("--employee_1_mean", type=float, default=20.0,
                        help="Mean service duration for Employee 1")
    parser.add_argument("--employee_1_stddev", type=float, default=0.0,
                        help="Standard deviation for service duration for Employee 1")
    parser.add_argument("--employee_2_mean", type=float, default=30.0,
                        help="Mean service duration for Employee 2")
    parser.add_argument("--employee_2_stddev", type=float, default=4.0,
                        help="Standard deviation for service duration for Employee 2")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducibility")

    args = parser.parse_args()
    
    sim = StoreSimulation(args)
    sim.run()

if __name__ == "__main__":
    main()