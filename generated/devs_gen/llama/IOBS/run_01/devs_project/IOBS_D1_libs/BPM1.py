"""Implementation of the BPM1 model."""

import json
import random
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class BPM1(Atomic):
    """BPM1 model: Receives successful password verification, generates random bill amount, and sends to TPM1."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "input"))
        self.add_out_port(Port(dict, "TPM1_in"))

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
        for item in self.input["input"].values():
            self.hold_in("PROCESSING", 0.0)
            break

    def lambdaf(self):
        self._write_event("bill", {
            "amount": random.randint(0, 40),
        })
        self.output["TPM1_in"].add({
            "amount": random.randint(0, 40),
        })
        self.hold_in("IDLE", 0.0)

    def deltint(self):
        self.passivate("IDLE")

    def exit(self):
        pass