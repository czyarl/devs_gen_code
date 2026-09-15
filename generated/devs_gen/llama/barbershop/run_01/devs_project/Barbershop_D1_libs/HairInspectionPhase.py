"""Complete pattern: Hair Inspection Phase."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class HairInspectionPhase(Atomic):
    """Hair Inspection Phase model."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "to_cut"))
        self.add_in_port(Port(dict, "cut_done"))
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
        for item in self.input["to_cut"].values:
            self.current_customer = dict(item)
            self.hold_in("BUSY", 7.0)
            break

        for item in self.input["cut_done"].values:
            self.current_customer = None
            self._write_event("service_completed", {
                "message": "done",
            })
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "BUSY":
            self.output["to_cut"].add(dict(cust_id=self.current_customer["cust_id"]))

    def deltint(self):
        if self.phase == "BUSY":
            self._write_event("inspection_completed", {
                "cust_id": self.current_customer["cust_id"],
            })
            self.hold_in("WAITING_FOR_CUT", 0.0)

    def exit(self):
        pass