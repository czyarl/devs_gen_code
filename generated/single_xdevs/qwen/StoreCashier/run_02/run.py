import argparse
import json
import math
import random
import sys
from datetime import datetime, timedelta

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Utility to format time as HH:MM:SS:mmm
def format_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millisecs = int((seconds % 1) * 1000)
    return f"{hours:02}:{minutes:02}:{secs:02}:{millisecs:03}"

class ClientGenerator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, client_mean: float, client_stddev: float):
        super().__init__(name)
        self.parent = parent
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.client_id = 0
        self.arrival_time = 0.0
        self.add_out_port(Port(object, "client_generated"))
        self.hold_in("INIT", 0)

    def initialize(self):
        self.client_id = 1
        self.arrival_time = 0.0
        self.hold_in("GENERATE", 0)

    def lambdaf(self):
        event = {
            "time": self.get_time(),
            "time_str": format_time(self.get_time()),
            "event": "client_generated",
            "entity_type": "client_generator",
            "entity": "ClientGenerator",
            "payload": {
                "client_id": self.client_id,
                "arrival_time": self.arrival_time
            }
        }
        self.output["client_generated"].add(event)

    def deltint(self):
        # Generate next client
        inter_arrival = random.normalvariate(self.client_mean, self.client_stddev)
        inter_arrival = max(0, inter_arrival)
        self.arrival_time += inter_arrival
        self.client_id += 1
        self.hold_in("GENERATE", inter_arrival)

    def deltext(self, e):
        pass

    def exit(self):
        pass

class Queue(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.waiting_clients = []
        self.add_in_port(Port(object, "client_generated"))
        self.add_in_port(Port(object, "employee_available"))
        self.add_out_port(Port(object, "client_paired"))
        self.hold_in("INIT", 0)

    def initialize(self):
        self.waiting_clients = []
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("IDLE", 0)

    def deltext(self, e):
        if e == "client_generated":
            client_event = self.input["client_generated"].values[0]
            self.waiting_clients.append(client_event)
            # Check if any employee is available
            if self.input["employee_available"].values:
                self.pair_client()
        elif e == "employee_available":
            # Check if any client is waiting
            if self.waiting_clients:
                self.pair_client()
        self.hold_in("IDLE", 0)

    def pair_client(self):
        if not self.waiting_clients:
            return
        # FIFO
        client_event = self.waiting_clients[0]
        employee_event = self.input["employee_available"].values[0]
        employee_id = employee_event["payload"]["employee_id"]
        # Remove from waiting list
        self.waiting_clients.pop(0)
        # Emit paired event
        paired_event = {
            "time": self.get_time(),
            "time_str": format_time(self.get_time()),
            "event": "client_paired",
            "entity_type": "queue",
            "entity": "Queue",
            "payload": {
                "client_id": client_event["payload"]["client_id"],
                "employee_id": employee_id,
                "paired_time": self.get_time()
            }
        }
        self.output["client_paired"].add(paired_event)

    def exit(self):
        pass

class Employee(Atomic):
    def __init__(self, name: str, parent: Coupled | None, employee_id: int, mean: float, stddev: float):
        super().__init__(name)
        self.parent = parent
        self.employee_id = employee_id
        self.mean = mean
        self.stddev = stddev
        self.current_client = None
        self.available_at = 0.0
        self.add_in_port(Port(object, "client_paired"))
        self.add_out_port(Port(object, "employee_available"))
        self.add_out_port(Port(object, "client_served"))
        self.hold_in("INIT", 0)

    def initialize(self):
        self.current_client = None
        self.available_at = 0.0
        self.hold_in("AVAILABLE", 0)

    def lambdaf(self):
        if self.current_client:
            # Emit served event
            served_event = {
                "time": self.get_time(),
                "time_str": format_time(self.get_time()),
                "event": "client_served",
                "entity_type": "employee",
                "entity": f"Employee_{self.employee_id}",
                "payload": {
                    "client_id": self.current_client["payload"]["client_id"],
                    "employee_id": self.employee_id,
                    "arrived": self.current_client["payload"]["arrival_time"],
                    "dispatched": self.get_time(),
                    "delay": self.get_time() - self.current_client["payload"]["arrival_time"]
                }
            }
            self.output["client_served"].add(served_event)
            # Emit available event
            available_event = {
                "time": self.get_time(),
                "time_str": format_time(self.get_time()),
                "event": "employee_available",
                "entity_type": "employee",
                "entity": f"Employee_{self.employee_id}",
                "payload": {
                    "employee_id": self.employee_id
                }
            }
            self.output["employee_available"].add(available_event)

    def deltint(self):
        if self.current_client:
            self.current_client = None
            self.hold_in("AVAILABLE", 0)
        else:
            self.hold_in("AVAILABLE", float('inf'))

    def deltext(self, e):
        if e == "client_paired":
            paired_event = self.input["client_paired"].values[0]
            if paired_event["payload"]["employee_id"] == self.employee_id:
                self.current_client = paired_event
                # Calculate service duration
                if self.stddev == 0:
                    duration = self.mean
                else:
                    duration = random.normalvariate(self.mean, self.stddev)
                    duration = max(self.mean - 3 * self.stddev, min(self.mean + 3 * self.stddev, duration))
                self.hold_in("SERVING", duration)
        else:
            self.hold_in("AVAILABLE", 0)

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, client_mean: float, client_stddev: float,
                 employee_1_mean: float, employee_1_stddev: float,
                 employee_2_mean: float, employee_2_stddev: float):
        super().__init__(name)
        self.parent = parent

        # Create components
        self.client_generator = ClientGenerator("ClientGenerator", self, client_mean, client_stddev)
        self.queue = Queue("Queue", self)
        self.employee_1 = Employee("Employee_1", self, 1, employee_1_mean, employee_1_stddev)
        self.employee_2 = Employee("Employee_2", self, 2, employee_2_mean, employee_2_stddev)

        self.add_component(self.client_generator)
        self.add_component(self.queue)
        self.add_component(self.employee_1)
        self.add_component(self.employee_2)

        # Define couplings
        self.add_coupling(self.client_generator.output["client_generated"], self.queue.input["client_generated"])
        self.add_coupling(self.employee_1.output["employee_available"], self.queue.input["employee_available"])
        self.add_coupling(self.employee_2.output["employee_available"], self.queue.input["employee_available"])
        self.add_coupling(self.queue.output["client_paired"], self.employee_1.input["client_paired"])
        self.add_coupling(self.queue.output["client_paired"], self.employee_2.input["client_paired"])
        self.add_coupling(self.employee_1.output["client_served"], self.output["client_served"])
        self.add_coupling(self.employee_2.output["client_served"], self.output["client_served"])

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000")
    parser.add_argument("--client_mean", type=float, default=10.0)
    parser.add_argument("--client_stddev", type=float, default=5.0)
    parser.add_argument("--employee_1_mean", type=float, default=20.0)
    parser.add_argument("--employee_1_stddev", type=float, default=0.0)
    parser.add_argument("--employee_2_mean", type=float, default=30.0)
    parser.add_argument("--employee_2_stddev", type=float, default=4.0)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    # Parse simulation time
    time_parts = args.simulation_time.split(':')
    hours = int(time_parts[0])
    minutes = int(time_parts[1])
    seconds = int(time_parts[2])
    millisecs = int(time_parts[3])
    total_seconds = hours * 3600 + minutes * 60 + seconds + millisecs / 1000.0

    # Set seed if provided
    if args.seed is not None:
        random.seed(args.seed)

    # Create system
    root = System("system", None,
                  args.client_mean, args.client_stddev,
                  args.employee_1_mean, args.employee_1_stddev,
                  args.employee_2_mean, args.employee_2_stddev)

    # Create coordinator
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()

    # Add output port to system to capture served events
    # We will manually output these in the main loop to ensure they are printed in order
    coord.add_output_port("client_served")

    # Simulate
    coord.simulate_time(total_seconds)

    # The simulation is complete, and all events have been printed via lambdaf in their respective models
    # Nothing else to do here

if __name__ == "__main__":
    main()