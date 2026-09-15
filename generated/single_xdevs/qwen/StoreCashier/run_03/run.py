import argparse
import json
import sys
import math
import random
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

# Helper function to format time as HH:MM:SS:mmm
def format_time(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millisecs = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}:{millisecs:03d}"

class ClientGenerator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, client_mean: float, client_stddev: float):
        super().__init__(name)
        self.parent = parent
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.client_id = 0
        self.next_arrival = 0.0

        # Ports
        self.add_out_port(Port(object, "client_generated"))
        self.add_out_port(Port(object, "client_paired"))

        # Initial state
        self.hold_in("GENERATE", 0)

    def initialize(self):
        self.client_id = 1
        self.next_arrival = 0.0
        self.hold_in("GENERATE", 0)

    def lambdaf(self):
        if self.phase == "GENERATE":
            payload = {
                "client_id": self.client_id,
                "arrival_time": self.next_arrival
            }
            self.output["client_generated"].add(payload)
            self.client_id += 1

    def deltint(self):
        if self.phase == "GENERATE":
            # Generate next client arrival time
            interval = random.gauss(self.client_mean, self.client_stddev)
            # Ensure non-negative interval
            interval = max(0, interval)
            self.next_arrival += interval
            self.hold_in("GENERATE", interval)

    def deltext(self, e):
        # No external inputs
        pass

    def exit(self):
        pass

class Queue(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.waiting_clients = []
        self.employee_1_available = True
        self.employee_2_available = True

        # Ports
        self.add_in_port(Port(object, "client_generated"))
        self.add_in_port(Port(object, "employee_available"))
        self.add_out_port(Port(object, "client_paired"))

        # Initial state
        self.hold_in("IDLE", 0)

    def initialize(self):
        self.waiting_clients = []
        self.employee_1_available = True
        self.employee_2_available = True
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        # Check if we can pair clients with available employees
        if self.waiting_clients and (self.employee_1_available or self.employee_2_available):
            # Process FIFO
            client = self.waiting_clients[0]
            paired = False
            if self.employee_1_available:
                self.employee_1_available = False
                payload = {
                    "client_id": client["client_id"],
                    "employee_id": 1,
                    "paired_time": self.time
                }
                self.output["client_paired"].add(payload)
                self.waiting_clients.pop(0)
                paired = True
            elif self.employee_2_available:
                self.employee_2_available = False
                payload = {
                    "client_id": client["client_id"],
                    "employee_id": 2,
                    "paired_time": self.time
                }
                self.output["client_paired"].add(payload)
                self.waiting_clients.pop(0)
                paired = True
            if paired:
                self.hold_in("IDLE", 0)
            else:
                self.hold_in("IDLE", float('inf'))
        else:
            self.hold_in("IDLE", float('inf'))

    def deltext(self, e):
        if e == "client_generated":
            # Add to waiting list
            for value in self.input["client_generated"].values:
                self.waiting_clients.append({
                    "client_id": value["client_id"],
                    "arrival_time": value["arrival_time"]
                })
            # Try to pair if possible
            if self.employee_1_available or self.employee_2_available:
                self.hold_in("IDLE", 0)
            else:
                self.hold_in("IDLE", float('inf'))
        elif e == "employee_available":
            # Update availability
            for value in self.input["employee_available"].values:
                if value["employee_id"] == 1:
                    self.employee_1_available = True
                elif value["employee_id"] == 2:
                    self.employee_2_available = True
            # Try to pair if possible
            if self.waiting_clients and (self.employee_1_available or self.employee_2_available):
                self.hold_in("IDLE", 0)
            else:
                self.hold_in("IDLE", float('inf'))

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
        self.is_available = True

        # Ports
        self.add_in_port(Port(object, "client_paired"))
        self.add_out_port(Port(object, "employee_available"))
        self.add_out_port(Port(object, "client_served"))

        # Initial state
        self.hold_in("IDLE", 0)

    def initialize(self):
        self.current_client = None
        self.is_available = True
        self.hold_in("IDLE", 0)

    def lambdaf(self):
        if self.phase == "SERVING":
            # Emit client served event
            payload = {
                "client_id": self.current_client["client_id"],
                "employee_id": self.employee_id,
                "arrived": self.current_client["arrival_time"],
                "dispatched": self.time,
                "delay": self.time - self.current_client["arrival_time"]
            }
            self.output["client_served"].add(payload)

    def deltint(self):
        if self.phase == "SERVING":
            # Service complete
            self.is_available = True
            # Emit employee available
            payload = {
                "employee_id": self.employee_id
            }
            self.output["employee_available"].add(payload)
            self.current_client = None
            self.hold_in("IDLE", 0)
        elif self.phase == "IDLE":
            # If there's a waiting client, start serving
            # This is handled in deltext
            pass

    def deltext(self, e):
        if e == "client_paired":
            for value in self.input["client_paired"].values:
                if value["employee_id"] == self.employee_id:
                    self.current_client = {
                        "client_id": value["client_id"],
                        "arrival_time": value["paired_time"]
                    }
                    # Calculate service duration
                    duration = random.gauss(self.mean, self.stddev)
                    # Ensure duration is within bounds
                    if self.stddev > 0:
                        min_duration = self.mean - 3 * self.stddev
                        max_duration = self.mean + 3 * self.stddev
                        duration = max(min_duration, min(duration, max_duration))
                    else:
                        duration = self.mean
                    self.hold_in("SERVING", duration)
                    break
        elif e == "employee_available":
            # This is for the model to know the employee is available
            pass

    def exit(self):
        pass

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, 
                 client_mean: float, client_stddev: float,
                 employee_1_mean: float, employee_1_stddev: float,
                 employee_2_mean: float, employee_2_stddev: float):
        super().__init__(name)
        self.parent = parent

        # Instantiate sub-models
        self.client_generator = ClientGenerator("ClientGenerator", self, client_mean, client_stddev)
        self.queue = Queue("Queue", self)
        self.employee_1 = Employee("Employee_1", self, 1, employee_1_mean, employee_1_stddev)
        self.employee_2 = Employee("Employee_2", self, 2, employee_2_mean, employee_2_stddev)

        self.add_component(self.client_generator)
        self.add_component(self.queue)
        self.add_component(self.employee_1)
        self.add_component(self.employee_2)

        # Define couplings
        # Client Generator -> Queue
        self.add_coupling(self.client_generator.output["client_generated"], self.queue.input["client_generated"])
        # Queue -> Employee
        self.add_coupling(self.queue.output["client_paired"], self.employee_1.input["client_paired"])
        self.add_coupling(self.queue.output["client_paired"], self.employee_2.input["client_paired"])
        # Employee -> Queue
        self.add_coupling(self.employee_1.output["employee_available"], self.queue.input["employee_available"])
        self.add_coupling(self.employee_2.output["employee_available"], self.queue.input["employee_available"])
        # Employee -> Output
        self.add_coupling(self.employee_1.output["client_served"], self.output["client_served"])
        self.add_coupling(self.employee_2.output["client_served"], self.output["client_served"])

    def initialize(self):
        pass

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000")
    parser.add_argument("--client_mean", type=float, default=10.0)
    parser.add_argument("--client_stddev", type=float, default=5.0)
    parser.add_argument("--employee_1_mean", type=float, default=20.0)
    parser.add_argument("--employee_1_stddev", type=float, default=0.0)
    parser.add_argument("--employee_2_mean", type=float, default=30.0)
    parser.add_argument("--employee_2_stddev", type=float, default=4.0)
    parser.add_argument("--seed", type=int, required=False)

    args = parser.parse_args()

    # Parse simulation time
    time_parts = args.simulation_time.split(":")
    hours = int(time_parts[0])
    minutes = int(time_parts[1])
    seconds = int(time_parts[2])
    milliseconds = int(time_parts[3])
    total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0

    # Set seed if provided
    if args.seed is not None:
        random.seed(args.seed)

    # Create system
    root = System(
        name="system",
        parent=None,
        client_mean=args.client_mean,
        client_stddev=args.client_stddev,
        employee_1_mean=args.employee_1_mean,
        employee_1_stddev=args.employee_1_stddev,
        employee_2_mean=args.employee_2_mean,
        employee_2_stddev=args.employee_2_stddev
    )

    # Create coordinator
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()

    # Run simulation
    coord.simulate_time(total_seconds)

if __name__ == "__main__":
    main()