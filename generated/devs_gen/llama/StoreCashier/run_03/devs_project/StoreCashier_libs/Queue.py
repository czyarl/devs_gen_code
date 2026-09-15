"""Complete implementation of the Queue model."""

import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class Queue(Atomic):
    """Manages the FIFO queue of waiting clients and pairs them with available employees."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "client_in"))
        self.add_out_port(Port(dict, "to_employees"))
        self.waiting_clients = deque()
        self.client_id = 0

    def initialize(self):
        self.waiting_clients = deque()
        self.client_id = 0
        self.passivate("WAITING")

    def deltext(self, e):
        if self.phase == "WAITING":
            self.continuef(e)
            return

        for client in self.input["client_in"].values:
            self.waiting_clients.append(client)
            self.client_id += 1

    def lambdaf(self):
        if not self.waiting_clients:
            return

        client = self.waiting_clients.popleft()
        employee_id = 1 if len(self.output["to_employees"].values) == 0 else 2
        paired_time = get_current_time()
        assignment = {
            "client_id": client["client_id"],
            "arrival_time": client["arrival_time"],
            "employee_id": employee_id,
            "paired_time": paired_time,
        }
        self.output["to_employees"].add(assignment)

        print(json.dumps({
            "time": get_current_time(),
            "event": "client_paired",
            "payload": {
                "client_id": client["client_id"],
                "employee_id": employee_id,
                "paired_time": paired_time,
            }
        }), flush=True)

    def deltint(self):
        pass

    def exit(self):
        pass