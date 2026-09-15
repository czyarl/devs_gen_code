"""Atomic DEVS model for the HairCuttingPhase."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class HairCuttingPhase(Atomic):
    """Accepts a customer from HairInspectionPhase, holds for cutting_duration, and emits done signal."""

    def __init__(self, name: str, parent: Coupled | None, cutting_duration: float):
        super().__init__(name)
        self.parent = parent
        self.cutting_duration = cutting_duration
        self.add_in_port(Port(dict, "in"))
        self.add_out_port(Port(dict, "out"))
        self.customer = None
        self.customer_count = 0

    def initialize(self):
        self.customer = None
        self.customer_count = 0
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        for packet in self.input["in"].values:
            self.customer = dict(packet)
            self.hold_in("PROCESSING", self.cutting_duration)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.customer is not None:
            self.output["out"].add({"time": get_current_time(), "event": "done"})
            self.customer_count += 1
            record = {
                "time": get_current_time(),
                "type": "state",
                "model": "cuthair",
                "field": "total customer done",
                "value": self.customer_count
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        self.customer = None
        self.passivate("IDLE")

    def exit(self):
        pass