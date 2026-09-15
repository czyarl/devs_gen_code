import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class FleetCoordinator(Atomic):
    """Monitors aircraft availability and cargo demand."""

    def __init__(self, name: str, parent: Coupled | None, num_aircraft: int):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "aircraft_idle"))
        self.add_out_port(Port(dict, "assignment_created"))
        self.num_aircraft = num_aircraft
        self.aircraft_idle = []
        self.pallet_queue = []

    def initialize(self):
        self.aircraft_idle = []
        self.pallet_queue = []
        self.passivate("IDLE")

    def deltext(self, e):
        for packet in self.input["aircraft_idle"].values:
            self.aircraft_idle.append(packet["aircraft_id"])

        if self.phase == "IDLE" and self.aircraft_idle and self.pallet_queue:
            self.hold_in("ASSIGNMENT_NEEDED", 0.0)
        elif self.phase != "IDLE":
            self.continuef(e)

    def lambdaf(self):
        if self.phase == "ASSIGNMENT_NEEDED":
            aircraft_id = self.aircraft_idle.pop(0)
            pallet_id = self.pallet_queue.pop(0)
            payload = {
                "aircraft_id": aircraft_id,
                "pallet_id": pallet_id,
            }
            print(json.dumps({
                "time": get_current_time(),
                "entity": "coordinator",
                "event": "assignment_created",
                "payload": payload,
            }), flush=True)
            self.output["assignment_created"].add(payload)

    def deltint(self):
        if self.phase != "ASSIGNMENT_NEEDED":
            self.passivate("IDLE")
            return

    def exit(self):
        pass