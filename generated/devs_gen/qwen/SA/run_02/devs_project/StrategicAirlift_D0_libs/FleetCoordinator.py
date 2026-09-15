"""FleetCoordinator model for airfreight logistics simulation."""

import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class FleetCoordinator(Atomic):
    """Monitor aircraft availability and pallet demand to assign cargo to idle aircraft."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "aircraft_idle_in"))
        self.add_in_port(Port(dict, "pallet_available_in"))
        self.add_out_port(Port(dict, "assignment_out"))
        self.add_out_port(Port(dict, "aircraft_request_out"))
        self.idle_aircraft = set()
        self.pallet_queue = deque()
        self.prepared_assignment = None

    def initialize(self):
        self.idle_aircraft = set()
        self.pallet_queue = deque()
        self.prepared_assignment = None
        self.passivate("WAITING")

    def _prepare_assignment_if_possible(self) -> None:
        if not self.idle_aircraft or not self.pallet_queue:
            self.passivate("WAITING")
            return
        pallet = self.pallet_queue.popleft()
        aircraft_id = min(self.idle_aircraft)
        self.idle_aircraft.remove(aircraft_id)
        self.prepared_assignment = {
            "aircraft_id": aircraft_id,
            "pallet_id": pallet["pallet_id"],
            "generation_time": pallet.get("generation_time", 0.0)
        }
        self.hold_in("OUTPUT_READY", 0.0)

    def deltext(self, e):
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        for aircraft_notice in self.input["aircraft_idle_in"].values:
            self.idle_aircraft.add(int(aircraft_notice["aircraft_id"]))
        for pallet_notice in self.input["pallet_available_in"].values:
            self.pallet_queue.append(dict(pallet_notice))

        self._prepare_assignment_if_possible()

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        assignment = dict(self.prepared_assignment)
        self.output["assignment_out"].add(assignment)
        self.output["aircraft_request_out"].add({"aircraft_id": assignment["aircraft_id"]})

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
        self._prepare_assignment_if_possible()

    def exit(self):
        pass