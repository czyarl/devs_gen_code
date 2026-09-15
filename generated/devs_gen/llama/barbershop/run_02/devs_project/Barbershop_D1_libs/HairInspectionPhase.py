"""Complete pattern: Hair Inspection Phase model."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class HairInspectionPhase(Atomic):
    """Coordinates with the Reception Desk, performs hair inspection, and sends customers to the Hair Cutting Phase."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "cust"))
        self.add_in_port(Port(dict, "queue_status"))
        self.add_out_port(Port(dict, "to_cut"))
        self.add_out_port(Port(dict, "to_reception"))
        self.current_customer = None

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "event": event,
            "payload": payload,
        }), flush=True)

    def initialize(self):
        self.current_customer = None
        self.passivate("IDLE")

    def deltext(self, e):
        was_idle = self.phase == "IDLE"
        if was_idle:
            self.continuef(e)

        for item in self.input["cust"].values:
            if self.current_customer is None:
                self.current_customer = dict(item)
                self._write_event("customer_inspected", {
                    "customer_id": self.current_customer["content"],
                })
                self.hold_in("INSPECTING", 7.0)

        for _ in self.input["queue_status"].values:
            pass  # No specific action required

    def lambdaf(self):
        if self.phase == "OUTPUT_READY":
            self.output["to_cut"].add(dict(self.current_customer))

    def deltint(self):
        if self.phase == "INSPECTING":
            self._write_event("inspection_completed", {
                "customer_id": self.current_customer["content"],
            })
            self.output["to_reception"].add({"content": "done"})
            self.current_customer = None
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase == "OUTPUT_READY":
            self.passivate("IDLE")

    def exit(self):
        pass