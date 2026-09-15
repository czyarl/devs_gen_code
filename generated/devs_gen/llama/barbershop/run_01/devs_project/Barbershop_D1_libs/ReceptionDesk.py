"""Complete pattern: ReceptionDesk Atomic DEVS model."""

import json
import sys
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ReceptionDesk(Atomic):
    """Manages the reception desk, processes customers, and sends them to the hair inspection phase."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "cust_in"))
        self.add_out_port(Port(dict, "cust"))
        self.add_out_port(Port(dict, "to_reception"))
        self.add_out_port(Port(dict, "reception_output"))
        self.queue = deque()
        self.total_customers = 0

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "event": event,
            "payload": payload,
        }), flush=True)

    def initialize(self):
        self.queue = deque()
        self.total_customers = 0
        self._write_event("state", {"total customers num": 0})
        self.passivate("IDLE")

    def deltext(self, e):
        for customer in self.input["cust_in"].values:
            if len(self.queue) < 8:
                self.queue.append(customer["cust_id"])
                self.total_customers += 1
                self._write_event("state", {"total customers num": self.total_customers})
                self._write_event("message", {"message": f"Customer {customer['cust_id']} accepted"})
                self.hold_in("PROCESSING", 5.0)

    def lambdaf(self):
        if self.phase == "PROCESSING":
            customer = self.queue.popleft()
            self._write_event("message", {"message": f"Customer {customer} processed"})
            self.output["cust"].add({"cust_id": customer})

    def deltint(self):
        if self.phase == "PROCESSING":
            self.passivate("IDLE")

    def exit(self):
        pass