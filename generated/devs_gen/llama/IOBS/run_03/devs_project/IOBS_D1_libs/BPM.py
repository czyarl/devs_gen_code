"""Complete implementation of the BPM atomic model."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import random


class BPM(Atomic):
    """BPM atomic model."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "verification_in"))
        self.add_out_port(Port(dict, "bill_out"))
        self.amount = None

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "model": self.name,
            "event": event,
            "data": payload,
        }), flush=True)

    def initialize(self):
        self.passivate("IDLE")

    def deltext(self, e):
        for packet in self.input["verification_in"].values:
            self.amount = random.randint(0, 40)
            self._write_event("bill", {"amount": self.amount})
            self.output["bill_out"].add({"amount": self.amount})
            self.passivate("IDLE")

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def exit(self):
        pass