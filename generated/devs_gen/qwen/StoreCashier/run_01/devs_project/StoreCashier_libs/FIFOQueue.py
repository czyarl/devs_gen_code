"""FIFO queue for assigning clients to available employees."""

import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class FIFOQueue(Atomic):
    """Maintain a FIFO queue of unpaired clients and assign them to available employees."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "client_in"))
        self.add_in_port(Port(dict, "employee_1_available"))
        self.add_in_port(Port(dict, "employee_2_available"))
        self.add_out_port(Port(dict, "to_employee_1"))
        self.add_out_port(Port(dict, "to_employee_2"))
        self.waiting = deque()
        self.employee_1_available = True
        self.employee_2_available = True
        self.prepared_assignment = None

    def initialize(self):
        self.waiting = deque()
        self.employee_1_available = True
        self.employee_2_available = True
        self.prepared_assignment = None
        # Both employees are available at t=0
        self.passivate("IDLE")

    def _prepare_assignment_if_possible(self) -> None:
        if not self.waiting or (not self.employee_1_available and not self.employee_2_available):
            self.passivate("IDLE")
            return

        client = self.waiting.popleft()
        paired_time = get_current_time()

        if self.employee_1_available:
            self.employee_1_available = False
            self.prepared_assignment = {
                "client_id": client["client_id"],
                "arrival_time": client["arrival_time"],
                "employee_id": 1,
                "paired_time": paired_time
            }
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.employee_2_available:
            self.employee_2_available = False
            self.prepared_assignment = {
                "client_id": client["client_id"],
                "arrival_time": client["arrival_time"],
                "employee_id": 2,
                "paired_time": paired_time
            }
            self.hold_in("OUTPUT_READY", 0.0)
        else:
            # Should not happen due to earlier check, but just in case
            self.waiting.appendleft(client)
            self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        # Receive new clients
        for client in self.input["client_in"].values:
            self.waiting.append(dict(client))

        # Receive employee availability signals
        for msg in self.input["employee_1_available"].values:
            self.employee_1_available = True
        for msg in self.input["employee_2_available"].values:
            self.employee_2_available = True

        self._prepare_assignment_if_possible()

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        assignment = self.prepared_assignment
        employee_id = assignment["employee_id"]

        # Emit to the appropriate employee
        if employee_id == 1:
            self.output["to_employee_1"].add(assignment)
        else:
            self.output["to_employee_2"].add(assignment)

        # Write pairing record to stdout
        record = {
            "time": get_current_time(),
            "time_str": f"{int(get_current_time()) // 3600:02d}:{(int(get_current_time()) % 3600) // 60:02d}:{int(get_current_time()) % 60:02d}:{int((get_current_time() % 1) * 1000):03d}",
            "event": "client_paired",
            "entity_type": "queue",
            "entity": "Queue",
            "payload": {
                "client_id": assignment["client_id"],
                "employee_id": employee_id,
                "paired_time": assignment["paired_time"]
            }
        }
        print(json.dumps(record), flush=True)

    def deltint(self):
        self.prepared_assignment = None
        self._prepare_assignment_if_possible()

    def exit(self):
        pass