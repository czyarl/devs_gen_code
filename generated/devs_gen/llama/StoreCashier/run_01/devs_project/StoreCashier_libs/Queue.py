"""Complete implementation: Manage a FIFO queue of clients waiting to be served by one of two employees."""

import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class Queue(Atomic):
    """Manage a FIFO queue of clients waiting to be served by one of two employees."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "client_in"))
        self.add_out_port(Port(dict, "to_employee_1"))
        self.add_out_port(Port(dict, "to_employee_2"))

        self.waiting = deque()
        self.employee_1_available = True
        self.employee_2_available = True

    def initialize(self):
        self.waiting = deque()
        self.employee_1_available = True
        self.employee_2_available = True
        self.passivate("WAITING")

    def deltext(self, e):
        if self.phase == "WAITING":
            self.continuef(e)
            return

        for client in self.input["client_in"].values:
            self.waiting.append(client)
        self._assign_client()

    def _assign_client(self):
        if not self.waiting:
            self.passivate("WAITING")
            return

        if self.employee_1_available and self.employee_2_available:
            client = self.waiting.popleft()
            if client["arrival_time"] < get_current_time():
                print("Error: Client arrived in the past.", flush=True)
                return
            if self.employee_1_available:
                self._assign_client_to_employee(client, 1)
            else:
                self._assign_client_to_employee(client, 2)
        elif self.employee_1_available:
            if self.waiting:
                client = self.waiting.popleft()
                self._assign_client_to_employee(client, 1)
        elif self.employee_2_available:
            if self.waiting:
                client = self.waiting.popleft()
                self._assign_client_to_employee(client, 2)

    def _assign_client_to_employee(self, client, employee_id):
        client["paired_time"] = get_current_time()
        if employee_id == 1:
            self.employee_1_available = False
            self.output["to_employee_1"].add(client)
        else:
            self.employee_2_available = False
            self.output["to_employee_2"].add(client)

        print(json.dumps({
            "time": get_current_time(),
            "event": "client_paired",
            "payload": {
                "client_id": client["client_id"],
                "employee_id": employee_id,
                "paired_time": client["paired_time"]
            }
        }), flush=True)

    def deltint(self):
        pass

    def exit(self):
        pass