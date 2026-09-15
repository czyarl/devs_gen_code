import argparse
import json
import math
import random
import sys
from datetime import datetime, timedelta

from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock


class ClientGenerator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, client_mean: float, client_stddev: float):
        super().__init__(name)
        self.parent = parent
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.client_id = 0
        self.next_arrival = 0.0
        self.add_out_port(Port(object, "client_generated"))
        self.hold_in("INIT", 0)

    def initialize(self):
        self.client_id = 1
        self.next_arrival = self.client_mean
        self.hold_in("WAIT", 0)

    def lambdaf(self):
        self.output["client_generated"].add({
            "client_id": self.client_id,
            "arrival_time": self.time_last
        })

    def deltint(self):
        # Generate next client
        self.client_id += 1
        # Sample inter-arrival time
        if self.client_stddev > 0:
            inter_arrival = random.gauss(self.client_mean, self.client_stddev)
            inter_arrival = max(0, inter_arrival)
        else:
            inter_arrival = self.client_mean
        self.next_arrival += inter_arrival
        self.hold_in("WAIT", inter_arrival)

    def deltext(self, e):
        # No external inputs
        pass

    def exit(self):
        pass


class Queue(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(object, "client_generated"))
        self.add_in_port(Port(object, "employee_available"))
        self.add_out_port(Port(object, "client_paired"))
        self.add_out_port(Port(object, "employee_available"))
        self.waiting_clients = []
        self.available_employees = set()
        self.hold_in("INIT", 0)

    def initialize(self):
        self.hold_in("WAIT", 0)

    def lambdaf(self):
        # Output any paired clients or available employees
        if self.waiting_clients:
            # Check if any employees are available
            if self.available_employees:
                # Pair the first waiting client with first available employee
                client = self.waiting_clients.pop(0)
                emp_id = self.available_employees.pop()
                self.output["client_paired"].add({
                    "client_id": client["client_id"],
                    "employee_id": emp_id,
                    "paired_time": self.time_last
                })
                # Output that employee is now busy
                self.output["employee_available"].add({
                    "employee_id": emp_id
                })

    def deltint(self):
        self.hold_in("WAIT", 0)

    def deltext(self, e):
        if e == "client_generated":
            # Add client to waiting list
            client = self.input["client_generated"].values[0]
            self.waiting_clients.append(client)
        elif e == "employee_available":
            # Add employee to available set
            emp = self.input["employee_available"].values[0]
            self.available_employees.add(emp["employee_id"])

        # Check if we can pair any clients
        if self.waiting_clients and self.available_employees:
            # Output paired event
            self.hold_in("PROCESS", 0)
        else:
            self.hold_in("WAIT", 0)

    def exit(self):
        pass


class Employee(Atomic):
    def __init__(self, name: str, parent: Coupled | None, employee_id: int, mean: float, stddev: float):
        super().__init__(name)
        self.parent = parent
        self.employee_id = employee_id
        self.mean = mean
        self.stddev = stddev
        self.add_in_port(Port(object, "client_paired"))
        self.add_out_port(Port(object, "client_served"))
        self.add_out_port(Port(object, "employee_available"))
        self.current_client = None
        self.service_end_time = 0.0
        self.hold_in("INIT", 0)

    def initialize(self):
        # Employee is initially available
        self.hold_in("AVAILABLE", 0)

    def lambdaf(self):
        if self.current_client is not None:
            # Output served event
            client = self.current_client
            self.output["client_served"].add({
                "client_id": client["client_id"],
                "employee_id": self.employee_id,
                "arrived": client["arrival_time"],
                "dispatched": self.time_last,
                "delay": self.time_last - client["arrival_time"]
            })
            # Output that employee is now available
            self.output["employee_available"].add({
                "employee_id": self.employee_id
            })

    def deltint(self):
        if self.current_client is not None:
            # Service completed
            self.current_client = None
            self.hold_in("AVAILABLE", 0)
        else:
            # Employee was already available
            self.hold_in("AVAILABLE", 0)

    def deltext(self, e):
        if e == "client_paired":
            # Start serving the client
            client = self.input["client_paired"].values[0]
            self.current_client = client
            # Sample service duration
            if self.stddev > 0:
                duration = random.gauss(self.mean, self.stddev)
                duration = max(self.mean - 3 * self.stddev, min(self.mean + 3 * self.stddev, duration))
            else:
                duration = self.mean
            self.service_end_time = self.time_last + duration
            self.hold_in("SERVING", duration)
        else:
            # No other inputs
            self.hold_in("AVAILABLE", 0)

    def exit(self):
        pass


class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, client_mean: float, client_stddev: float,
                 employee_1_mean: float, employee_1_stddev: float, employee_2_mean: float, employee_2_stddev: float):
        super().__init__(name)
        self.parent = parent
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.employee_1_mean = employee_1_mean
        self.employee_1_stddev = employee_1_stddev
        self.employee_2_mean = employee_2_mean
        self.employee_2_stddev = employee_2_stddev

        # Instantiate sub-models
        self.client_generator = ClientGenerator("ClientGenerator", self, client_mean, client_stddev)
        self.queue = Queue("Queue", self)
        self.employee1 = Employee("Employee_1", self, 1, employee_1_mean, employee_1_stddev)
        self.employee2 = Employee("Employee_2", self, 2, employee_2_mean, employee_2_stddev)

        self.add_component(self.client_generator)
        self.add_component(self.queue)
        self.add_component(self.employee1)
        self.add_component(self.employee2)

        # Define couplings
        # ClientGenerator -> Queue
        self.add_coupling(self.client_generator.output["client_generated"], self.queue.input["client_generated"])

        # Queue -> Employee1
        self.add_coupling(self.queue.output["client_paired"], self.employee1.input["client_paired"])
        # Queue -> Employee2
        self.add_coupling(self.queue.output["client_paired"], self.employee2.input["client_paired"])

        # Employee1 -> Queue
        self.add_coupling(self.employee1.output["employee_available"], self.queue.input["employee_available"])
        # Employee2 -> Queue
        self.add_coupling(self.employee2.output["employee_available"], self.queue.input["employee_available"])

        # Queue -> Employee1
        self.add_coupling(self.queue.output["employee_available"], self.employee1.input["employee_available"])
        # Queue -> Employee2
        self.add_coupling(self.queue.output["employee_available"], self.employee2.input["employee_available"])

        # Employee1 -> Output
        self.add_coupling(self.employee1.output["client_served"], self.output["client_served"])
        # Employee2 -> Output
        self.add_coupling(self.employee2.output["client_served"], self.output["client_served"])

        # Employee1 -> Queue
        self.add_coupling(self.employee1.output["employee_available"], self.queue.input["employee_available"])
        # Employee2 -> Queue
        self.add_coupling(self.employee2.output["employee_available"], self.queue.input["employee_available"])

        # Queue -> Output
        self.add_coupling(self.queue.output["client_paired"], self.output["client_paired"])

        # Employee1 -> Output
        self.add_coupling(self.employee1.output["employee_available"], self.output["employee_available"])
        # Employee2 -> Output
        self.add_coupling(self.employee2.output["employee_available"], self.output["employee_available"])

        # ClientGenerator -> Output
        self.add_coupling(self.client_generator.output["client_generated"], self.output["client_generated"])

        # Register output ports
        self.add_out_port(Port(object, "client_generated"))
        self.add_out_port(Port(object, "client_paired"))
        self.add_out_port(Port(object, "employee_available"))
        self.add_out_port(Port(object, "client_served"))


def format_time(time_val):
    """Convert simulation time to HH:MM:SS:mmm format."""
    hours = int(time_val // 3600)
    minutes = int((time_val % 3600) // 60)
    seconds = int(time_val % 60)
    milliseconds = int((time_val % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=str, default="00:05:00:000")
    parser.add_argument("--client_mean", type=float, default=10.0)
    parser.add_argument("--client_stddev", type=float, default=5.0)
    parser.add_argument("--employee_1_mean", type=float, default=20.0)
    parser.add_argument("--employee_1_stddev", type=float, default=0.0)
    parser.add_argument("--employee_2_mean", type=float, default=30.0)
    parser.add_argument("--employee_2_stddev", type=float, default=4.0)

    args = parser.parse_args()

    # Parse simulation time
    time_parts = args.simulation_time.split(":")
    hours = int(time_parts[0])
    minutes = int(time_parts[1])
    seconds = int(time_parts[2])
    milliseconds = int(time_parts[3])
    total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0

    # Set seed for reproducibility
    random.seed(42)

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

    # Initialize and simulate
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()

    # Simulate until horizon
    coord.simulate_time(total_seconds)

    # Print final output
    for event in coord.get_events():
        event_time = event.time
        event_type = event.type
        payload = event.payload
        time_str = format_time(event_time)
        output_event = {
            "time": event_time,
            "time_str": time_str,
            "event": event_type,
            "entity_type": payload["entity_type"],
            "entity": payload["entity"],
            "payload": payload["payload"]
        }
        print(json.dumps(output_event), file=sys.stdout, flush=True)


if __name__ == "__main__":
    main()