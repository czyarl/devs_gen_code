"""Fleet Coordinator for airfreight logistics simulation."""

import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class FleetCoordinator(Atomic):
    """Maintain a queue of available aircraft IDs and a FIFO queue of pallets from the LoadingQueue."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "available_in"))
        self.add_in_port(Port(dict, "claimed_in"))
        self.add_out_port(Port(dict, "claim_out"))
        self.add_out_port(Port(dict, "assignment_out"))
        self.aircraft_queue = deque()
        self.pallet_queue = deque()
        self.prepared_assignment = None

    def initialize(self):
        self.aircraft_queue = deque()
        self.pallet_queue = deque()
        self.prepared_assignment = None
        self.passivate("WAITING")

    def _prepare_if_possible(self) -> None:
        if not self.aircraft_queue or not self.pallet_queue:
            self.passivate("WAITING")
            return
        aircraft_id = self.aircraft_queue.popleft()
        pallet = self.pallet_queue.popleft()
        pallet["aircraft_id"] = aircraft_id
        self.prepared_assignment = pallet
        self.hold_in("OUTPUT_READY", 0.0)

    def deltext(self, e):
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        for aircraft in self.input["available_in"].values:
            self.aircraft_queue.append(int(aircraft["aircraft_id"]))
        for pallet in self.input["claimed_in"].values:
            self.pallet_queue.append(dict(pallet))

        self._prepare_if_possible()

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        assignment = dict(self.prepared_assignment)
        self.output["assignment_out"].add(assignment)

        print(json.dumps({
            "time": get_current_time(),
            "entity": "coordinator",
            "event": "assignment_created",
            "payload": {
                "aircraft_id": assignment["aircraft_id"],
                "pallet_id": assignment["pallet_id"]
            }
        }), flush=True)

    def deltint(self):
        self.prepared_assignment = None
        # Continue at zero delay while both queues can form another assignment.
        self._prepare_if_possible()

    def exit(self):
        pass