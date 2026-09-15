"""Complete pattern: Fleet Coordinator assigns pallets to available aircraft."""

import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class FleetCoordinator(Atomic):
    """Assign pallets to aircraft when available."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "aircraft_available"))
        self.add_out_port(Port(dict, "assignment_created"))
        self.waiting_pallets = deque()
        self.available_aircraft = set()

    def initialize(self):
        self.waiting_pallets = deque()
        self.available_aircraft = set()
        self.passivate("WAITING")

    def _prepare_if_possible(self) -> None:
        if not self.waiting_pallets or not self.available_aircraft:
            self.passivate("WAITING")
            return
        self.hold_in("OUTPUT_READY", 0.0)

    def deltext(self, e):
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        for aircraft in self.input["aircraft_available"].values:
            self.available_aircraft.add(int(aircraft["aircraft_id"]))

        self._prepare_if_possible()

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        aircraft_id = min(self.available_aircraft)
        pallet_id = self.waiting_pallets.popleft()
        self.available_aircraft.remove(aircraft_id)

        assignment = {"aircraft_id": aircraft_id, "pallet_id": pallet_id}
        self.output["assignment_created"].add(assignment)

        print(json.dumps({
            "time": get_current_time(),
            "entity": "coordinator",
            "event": "assignment_created",
            "payload": assignment,
        }), flush=True)

        self.hold_in("WAITING", 0.0)

    def deltint(self):
        pass

    def exit(self):
        pass