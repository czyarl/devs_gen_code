"""FIFO queue for assigning clients to employees."""

import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class FIFOQueue(Atomic):
    """Receive client arrivals in FIFO order, maintain an internal queue of unpaired clients, and assign each to the next available employee."""

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
        self.passivate("IDLE")

    def _prepare_assignment_if_possible(self) -> None:
        if not self.waiting:
            self.passivate("IDLE")
            return

        client = self.waiting[0]
        if self.employee_1_available:
            self.employee_1_available = False
            self.prepared_assignment = {
                "client_id": client["client_id"],
                "arrival_time": client["arrival_time"],
                "employee_id": 1,
                "paired_time": get_current_time()
            }
            self.waiting.popleft()
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.employee_2_available:
            self.employee_2_available = False
            self.prepared_assignment = {
                "client_id": client["client_id"],
                "arrival_time": client["arrival_time"],
                "employee_id": 2,
                "paired_time": get_current_time()
            }
            self.waiting.popleft()
            self.hold_in("OUTPUT_READY", 0.0)
        else:
            self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        for client in self.input["client_in"].values:
            self.waiting.append(dict(client))

        for notice in self.input["employee_1_available"].values:
            self.employee_1_available = True

        for notice in self.input["employee_2_available"].values:
            self.employee_2_available = True

        self._prepare_assignment_if_possible()

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        assignment = dict(self.prepared_assignment)
        if assignment["employee_id"] == 1:
            self.output["to_employee_1"].add(assignment)
        else:
            self.output["to_employee_2"].add(assignment)

        # Emit client_paired JSONL record
        record = {
            "time": get_current_time(),
            "time_str": f"{int(get_current_time()) // 3600:02d}:{(int(get_current_time()) % 3600) // 60:02d}:{int(get_current_time()) % 60:02d}:{int((get_current_time() % 1) * 1000):03d}",
            "event": "client_paired",
            "entity_type": "queue",
            "entity": "Queue",
            "payload": {
                "client_id": assignment["client_id"],
                "employee_id": assignment["employee_id"],
                "paired_time": assignment["paired_time"]
            }
        }
        print(json.dumps(record), flush=True)

    def deltint(self):
        self.prepared_assignment = None
        # Continue at zero delay while both queues can form another assignment.
        self._prepare_assignment_if_possible()

    def exit(self):
        pass