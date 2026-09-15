import argparse
import json
import random
import sys
from xdevs.models import Atomic, Coupled, Port
from xdevs.sim import Coordinator, SimulationClock
import numpy as np

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
        self.hold_in("WAIT", self.sample_interarrival())

    def lambdaf(self):
        payload = {"client_id": self.client_id, "arrival_time": self.time}
        self.output["out"].add(payload)
        print(json.dumps({"time": self.time, "time_str": self.format_time(self.time), "event": "client_generated", "entity_type": "client_generator", "entity": "ClientGenerator", "payload": payload}), file=sys.stdout, flush=True)

    def deltint(self):
        self.client_id += 1
        self.lambdaf()
        self.hold_in("WAIT", self.sample_interarrival())

    def deltext(self, e):
        pass

    def exit(self):
        pass

    def sample_interarrival(self):
        return np.random.normal(self.client_mean, self.client_stddev)


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
        payload = {"employee_id": self.employee_id}
        self.output["out"].add(payload)
        print(json.dumps({"time": self.time, "time_str": self.format_time(self.time), "event": "employee_available", "entity_type": "employee", "entity": self.name, "payload": payload}), file=sys.stdout, flush=True)

    def deltint(self):
        self.busy = False
        self.client_id = None
        self.paired_time = None
        self.lambdaf()
        self.hold_in("AVAILABLE", 0)

    def deltext(self, e):
        if "in" in e:
            for msg in e["in"]:
                self.client_id = msg["client_id"]
                self.paired_time = self.time
                self.busy = True
                payload = {"client_id": self.client_id, "employee_id": self.employee_id, "paired_time": self.paired_time}
                self.parent.output["client_paired"].add(payload)
                print(json.dumps({"time": self.time, "time_str": self.format_time(self.time), "event": "client_paired", "entity_type": "queue", "entity": "Queue", "payload": payload}), file=sys.stdout, flush=True)
                service_time = self.sample_service()
                self.hold_in("BUSY", service_time)

    def exit(self):
        pass

    def sample_service(self):
        return np.random.normal(self.employee_mean, self.employee_stddev)


class Queue(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port("client_generated", "in"))
        self.add_in_port(Port("employee_available", "in"))
        self.add_out_port(Port("client_paired", "out"))
        self.clients = []
        self.employees = {1: False, 2: False}

    def initialize(self):
        pass

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def deltext(self, e):
        if "in" in e:
            for msg in e["in"]:
                if msg["event"] == "client_generated":
                    self.clients.append(msg["payload"]["client_id"])
                    self.try_pair()
                elif msg["event"] == "employee_available":
                    employee_id = msg["payload"]["employee_id"]
                    self.employees[employee_id] = False
                    self.try_pair()

    def exit(self):
        pass

    def try_pair(self):
        if self.clients and not self.employees[1] and not self.employees[2]:
            client_id = self.clients.pop(0)
            if not self.employees[1]:
                employee_id = 1
                self.employees[1] = True
            else:
                employee_id = 2
                self.employees[2] = True
            payload = {"client_id": client_id, "employee_id": employee_id}
            self.output["out"].add(payload)


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
        self.add_coupling(self.client_generator.output["out"], self.queue.input["in"])
        self.add_coupling(self.employee_1.output["out"], self.queue.input["in"])
        self.add_coupling(self.employee_2.output["out"], self.queue.input["in"])
        self.add_coupling(self.queue.output["client_paired"], self.employee_1.input["in"])
        self.add_coupling(self.queue.output["client_paired"], self.employee_2.input["in"])
        self.add_coupling(self.employee_1.output["client_served"], self.output["client_served"])
        self.add_coupling(self.employee_2.output["client_served"], self.output["client_served"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulation_time", type=str, required=True)
    parser.add_argument("--client_mean", type=float, default=10.0)
    parser.add_argument("--client_stddev", type=float, default=5.0)
    parser.add_argument("--employee_1_mean", type=float, default=20.0)
    parser.add_argument("--employee_1_stddev", type=float, default=0.0)
    parser.add_argument("--employee_2_mean", type=float, default=30.0)
    parser.add_argument("--employee_2_stddev", type=float, default=4.0)
    args = parser.parse_args()

    hours, minutes, seconds, milliseconds = map(int, args.simulation_time.split(':'))
    simulation_time = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000

    root = System(name="system", parent=None, client_mean=args.client_mean, client_stddev=args.client_stddev, employee_1_mean=args.employee_1_mean, employee_1_stddev=args.employee_1_stddev, employee_2_mean=args.employee_2_mean, employee_2_stddev=args.employee_2_stddev)
    coord = Coordinator(root, clock=SimulationClock(0))
    coord.initialize()
    coord.simulate_time(simulation_time)

if __name__ == "__main__":
    main()