"""Fleet Coordinator model for airfreight logistics simulation."""

import json
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class FleetCoordinator(Atomic):
    """Monitors aircraft availability and pallet demand. Assigns pallets to idle aircraft and tracks aircraft states."""

    def __init__(self, name: str, parent: Coupled | None, num_aircraft: int):
        super().__init__(name)
        self.parent = parent
        self.num_aircraft = num_aircraft
        self.add_in_port(Port(dict, "aircraft_idle_in"))
        self.add_in_port(Port(dict, "pallet_claimed_in"))
        self.add_out_port(Port(dict, "assignment_out"))
        self.add_out_port(Port(dict, "pallet_request_out"))
        self.available_aircraft = deque()
        self.pallet_queue = deque()
        self.assignment_pending = False
        self.pending_assignment = None

    def initialize(self):
        self.available_aircraft = deque()
        self.pallet_queue = deque()
        self.assignment_pending = False
        self.pending_assignment = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "OUTPUT_READY":
            self.continuef(e)
            return

        # Process aircraft idle notifications
        for idle_notice in self.input["aircraft_idle_in"].values:
            aircraft_id = int(idle_notice["aircraft_id"])
            self.available_aircraft.append(aircraft_id)

        # Process pallet claims from LoadingQueue
        for pallet_claim in self.input["pallet_claimed_in"].values:
            self.pallet_queue.append(dict(pallet_claim))

        # Try to make an assignment
        self._attempt_assignment()

    def _attempt_assignment(self) -> None:
        if not self.available_aircraft or not self.pallet_queue:
            self.passivate("IDLE")
            return

        # Get next aircraft and pallet
        aircraft_id = self.available_aircraft.popleft()
        pallet = self.pallet_queue.popleft()

        # Prepare assignment
        self.pending_assignment = {
            "aircraft_id": aircraft_id,
            "pallet_id": pallet["pallet_id"],
            "generation_time": pallet["generation_time"]
        }

        # Emit assignment to the specific aircraft
        self.output["assignment_out"].add(dict(self.pending_assignment))

        # Emit assignment_created event to stdout
        assignment_event = {
            "time": get_current_time(),
            "entity": "coordinator",
            "event": "assignment_created",
            "payload": {
                "aircraft_id": aircraft_id,
                "pallet_id": pallet["pallet_id"]
            }
        }
        print(json.dumps(assignment_event), flush=True)

        # Schedule output emission
        self.hold_in("OUTPUT_READY", 0.0)

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        # Send pallet request to LoadingQueue
        request = {"aircraft_id": self.pending_assignment["aircraft_id"]}
        self.output["pallet_request_out"].add(request)

    def deltint(self):
        self.pending_assignment = None
        # Continue at zero delay while both queues can form another assignment.
        self._attempt_assignment()

    def exit(self):
        pass