"""Complete pattern: Cargo assignment to first available aircraft."""

import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class FleetCoordinator(Atomic):
    """Route each queued request to exactly one available aircraft."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "aircraft_available"))
        self.add_in_port(Port(dict, "assignment_created"))
        self.add_out_port(Port(dict, "assignment_created"))
        self.waiting = deque()
        self.available_aircraft = set()
        self.next_pallet = None

    def initialize(self):
        self.waiting = deque()
        self.available_aircraft = set()
        self.next_pallet = None
        self.passivate("WAITING")

    def _prepare_if_possible(self) -> None:
        if not self.waiting or not self.available_aircraft:
            self.passivate("WAITING")
            return
        self.next_pallet = self.waiting.popleft()
        available_aircraft = min(self.available_aircraft)
        self.available_aircraft.remove(available_aircraft)
        self.hold_in("OUTPUT_READY", 0.0)

    def deltext(self, e):
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        for aircraft in self.input["aircraft_available"].values:
            self.available_aircraft.add(aircraft["aircraft_id"])

        for pallet in self.input["assignment_created"].values:
            pass  # TODO: implement

        self._prepare_if_possible()

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        assignment = dict(self.next_pallet)
        assignment["aircraft_id"] = min(self.available_aircraft)
        self.output["assignment_created"].add(assignment)

        print(json.dumps({
            "time": get_current_time(),
            "event": "assignment_created",
            "payload": assignment,
        }), flush=True)

    def deltint(self):
        self.next_pallet = None
        # Continue at zero delay while both queues can form another assignment.
        self._prepare_if_possible()

    def exit(self):
        pass