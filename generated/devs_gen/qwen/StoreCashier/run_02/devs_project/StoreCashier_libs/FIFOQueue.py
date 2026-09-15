"""FIFOQueue model for managing client assignments to employees."""

import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class FIFOQueue(Atomic):
    """Receive generated clients in arrival order, maintain an internal FIFO queue of unpaired clients, and assign each client to the first available employee."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "client_in"))
        self.add_in_port(Port(dict, "employee_1_available"))
        self.add_in_port(Port(dict, "employee_2_available"))
        self.add_out_port(Port(dict, "to_employee_1"))
        self.add_out_port(Port(dict, "to_employee_2"))
        self.waiting = deque()
        self.employee_1_available = False
        self.employee_2_available = False
        self.prepared_assignment = None

    def initialize(self):
        self.waiting = deque()
        self.employee_1_available = True
        self.employee_2_available = True
        self.prepared_assignment = None
        self.passivate("WAITING")

    def _prepare_if_possible(self) -> None:
        if not self.waiting or not (self.employee_1_available or self.employee_2_available):
            self.passivate("WAITING")
            return

        client = self.waiting.popleft()
        paired_time = get_current_time()
        employee_id = 1 if self.employee_1_available else 2
        self.employee_1_available = False if employee_id == 1 else self.employee_1_available
        self.employee_2_available = False if employee_id == 2 else self.employee_2_available

        assignment = {
            "client_id": client["client_id"],
            "arrival_time": client["arrival_time"],
            "employee_id": employee_id,
            "paired_time": paired_time
        }

        self.prepared_assignment = (assignment, employee_id)
        self.hold_in("OUTPUT_READY", 0.0)

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

        self._prepare_if_possible()

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        assignment, employee_id = self.prepared_assignment
        if employee_id == 1:
            self.output["to_employee_1"].add(assignment)
        else:
            self.output["to_employee_2"].add(assignment)

        # Write client_paired record to stdout
        time_str = "{:02d}:{:02d}:{:02d}:{:03d}".format(
            int(get_current_time() // 3600),
            int((get_current_time() % 3600) // 60),
            int(get_current_time() % 60),
            int((get_current_time() % 1) * 1000)
        )
        record = {
            "time": get_current_time(),
            "time_str": time_str,
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
        self._prepare_if_possible()

    def exit(self):
        pass