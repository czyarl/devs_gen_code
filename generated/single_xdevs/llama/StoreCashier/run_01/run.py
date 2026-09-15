python
import argparse
import json
import logging
import math
import numpy as np
import random
import sys
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock

class ClientGenerator(Atomic):
    def __init__(self, name: str, parent: Coupled | None, client_mean: float, client_stddev: float):
        super().__init__(name)
        self.parent = parent
        self.client_mean = client_mean
        self.client_stddev = client_stddev
        self.client_id = 1
        self.add_out_port(Port("client_generated", "out"))

    def initialize(self):
        self.lambdaf()
        self.hold_in("WAIT", self.client_mean)

    def lambdaf(self):
        arrival_time = self.elapsed_time
        payload = {"client_id": self.client_id, "arrival_time": arrival_time}
        self.output["out"].add(payload)
        print(json.dumps({"time": arrival_time, "time_str": self.format_time(arrival_time), "event": "client_generated", "entity_type": "client_generator", "entity": "ClientGenerator", "payload": payload}), file=sys.stdout, flush=True)
        self.client_id += 1

    def deltint(self):
        interval = max(0, np.random.normal(self.client_mean, self.client_stddev))
        interval = min(max(interval, 0), self.client_mean + 5 * self.client_stddev)
        self.hold_in("WAIT", interval)

    def deltext(self, e):
        pass

    def exit(self):
        pass

class Employee(Atomic):
    def __init__(self, name: str, parent: Coupled | None, employee_mean: float, employee_stddev: float, employee_id: int):
        super().__init__(name)
        self.parent = parent
        self.employee_mean = employee_mean
        self.employee_stddev = employee_stddev
        self.employee_id = employee_id
        self.add_in_port(Port("client_paired", "in"))
        self.add_out_port(Port("employee_available", "out"))
        self.add_out_port(Port("client_served", "out"))
        self.busy = False
        self.client_id = None
        self.paired_time = None

    def initialize(self):
        self.lambdaf()
        self.hold_in("AVAILABLE", 0)

    def lambdaf(self):
        if not self.busy:
            payload = {"employee_id": self.employee_id}
            self.output["out"].add(payload)
            print(json.dumps({"time": self.elapsed_time, "time_str": self.format_time(self.elapsed_time), "event": "employee_available", "entity_type": "employee", "entity": self.name, "payload": payload}), file=sys.stdout, flush=True)

    def deltint(self):
        if self.busy:
            service_duration = max(self.employee_mean - 3 * self.employee_stddev, min(self.employee_mean + 3 * self.client_stddev, np.random.normal(self.employee_mean, self.employee_stddev)))
            self.hold_in("BUSY", service_duration)
        else:
            self.hold_in("AVAILABLE", 0)

    def deltext(self, e):
        if self.input["in"].has_message():
            client_id = self.input["in"].get_message()["client_id"]
            self.client_id = client_id
            self.paired_time = self.elapsed_time
            self.busy = True
            payload = {"client_id": client_id, "employee_id": self.employee_id, "paired_time": self.elapsed_time}
            print(json.dumps({"time": self.elapsed_time, "time_str": self.format_time(self.elapsed_time), "event": "client_paired", "entity_type": "queue", "entity": "Queue", "payload": payload}), file=sys.stdout, flush=True)
            self.hold_in("BUSY", 0)

    def exit(self):
        pass

    def format_time(self, time):
        hours = int(time // 3600)
        minutes = int((time % 3600) // 60)
        seconds = int(time % 60)
        milliseconds = int((time % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"

class Queue(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("client_generated", "in_client"))
        self.add_in_port(Port("employee_available", "in_employee"))
        self.add_out_port(Port("client_paired", "out"))
        self.clients = []
        self.employees = []

    def initialize(self):
        self.hold_in("WAIT", 0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("WAIT", 0)

    def deltext(self, e):
        if self.input["in_client"].has_message():
            client = self.input["in_client"].get_message()
            self.clients.append(client)
            self.try_pair_client_employee()
        if self.input["in_employee"].has_message():
            employee = self.input["in_employee"].get_message()
            self.employees.append(employee)
            self.try_pair_client_employee()

    def try_pair_client_employee(self):
        if self.clients and self.employees:
            client = self.clients.pop(0)
            employee = self.employees.pop(0)
            payload = {"client_id": client["client_id"], "employee_id": employee["employee_id"], "paired_time": self.elapsed_time}
            self.output["out"].add(payload)
            print(json.dumps({"time": self.elapsed_time, "time_str": self.format_time(self.elapsed_time), "event": "client_paired", "entity_type": "queue", "entity": "Queue", "payload": payload}), file=sys.stdout, flush=True)

    def exit(self):
        pass

    def format_time(self, time):
        hours = int(time // 3600)
        minutes = int((time % 3600) // 60)
        seconds = int(time % 60)
        milliseconds = int((time % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{milliseconds:03d}"

class System(Coupled):
    def __init__(self, name: str, parent: Coupled | None, client_mean: float, client_stddev: float, employee_1_mean: float, employee_1_stddev: float, employee_2_mean: float, employee_2_stddev: float):
        super().__init__(name)
        self.parent = parent
        self.client_generator = ClientGenerator(name="client_generator", parent=self, client_mean=client_mean, client_stddev=client_stddev)
        self.add_component(self.client_generator)
        self.queue = Queue(name="queue", parent=self)
        self.add_component(self.queue)
        self.employee_1 = Employee(name="Employee_1", parent=self, employee_mean=employee_1_mean, employee_stddev=employee_1_stddev, employee_id=1)
        self.add_component(self.employee_1)
        self.employee_2 = Employee(name="Employee_2", parent=self, employee_mean=employee_2_mean, employee_stddev=employee_2_stddev, employee_id=2)
        self.add_component(self.employee_2)
        self.add_coupling(self.client_generator.output["out"], self.queue.input["in_client"])
        self.add_coupling(self.employee_1.output["out"], self.queue.input["in_employee"])
        self.add_coupling(self.employee_2.output["out"], self.queue.input["in_employee"])
        self.add_coupling(self.queue.output["out"], self.employee_1.input["in"])
        self.add_coupling(self.queue.output["out"], self.employee_2.input["in"])
        self.employee_1.output["client_served"].add_callback(self.client_served)
        self.employee_2.output["client_served"].add_callback(self.client_served)

    def client_served(self, message):
        employee_id = message["employee_id"]
        client_id = message["client_id"]
        arrived = message["arrived"]
        dispatched = self.elapsed_time
        delay = dispatched - arrived
        service_duration = dispatched - self.get_component(f"Employee_{employee_id}").paired_time
        payload = {"client_id": client_id, "employee_id": employee_id, "arrived": arrived, "dispatched": dispatched, "delay": delay}
        print(json.dumps({"time": dispatched, "time_str": self.format_time(dispatched), "event": "client_served", "entity_type": "employee", "entity": f"Employee_{employee_id}", "payload": payload}), file=sys.stdout, flush=True)

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

    hours, minutes, seconds, milliseconds = map(int, args.simulation_time.split(':'))
    total_seconds = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000

    root = System(name="system", parent=None, client_mean=args.client_mean, client_stddev=args.client_stddev, employee_1_mean=args.employee_1_mean, employee_1_stddev=args.employee_1_stddev, employee_2_mean=args.employee_2_mean, employee_2_stddev=args.employee_2_stddev)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(total_seconds)

if __name__ == "__main__":
    main()
```