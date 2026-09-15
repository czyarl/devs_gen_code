"""Atomic DEVS model for HairCutting phase."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class HairCutting(Atomic):
    """Processes one customer at a time for exactly 20 seconds, then signals completion."""

    def __init__(self, name: str, parent: Coupled | None, cutting_time: float):
        super().__init__(name)
        self.parent = parent
        self.cutting_time = cutting_time
        self.add_in_port(Port(dict, "to_cut"))
        self.add_out_port(Port(str, "out"))
        self.in_flight = None
        self.total_customers_done = 0

    def initialize(self):
        self.in_flight = None
        self.total_customers_done = 0
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        for customer in self.input["to_cut"].values:
            self.in_flight = dict(customer)
            self.hold_in("PROCESSING", self.cutting_time)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.in_flight is not None:
            self.output["out"].add("done")
            # Emit state change record to stdout
            record = {
                "time": get_current_time(),
                "type": "state",
                "model": "cuthair",
                "field": "total customer done",
                "value": str(self.total_customers_done + 1)
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        if self.phase == "PROCESSING" and self.in_flight is not None:
            self.total_customers_done += 1
            self.in_flight = None
            self.passivate("IDLE")

    def exit(self):
        pass