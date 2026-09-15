"""Implementation of the PV1 Atomic DEVS model."""

import json
import random
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class PV1(Atomic):
    """Perform random password check and report results."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
    ):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "input"))
        self.add_out_port(Port(dict, "BPM1_in"))
        self.attempts = 0

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "model": self.name,
            "event": event,
            "data": payload,
        }), flush=True)

    def initialize(self):
        self.passivate("idle")

    def deltext(self, e):
        for packet in self.input["input"].values:
            self._write_event("verification", {
                "success": 1,
                "attempts": 0,  # Initialize attempts to 0 for new input
            })
            self.attempts = 0
            self.hold_in("processing", 10.0)

    def lambdaf(self):
        if self.phase != "processing":
            return

        # Perform random password check
        if random.random() < 0.5:  # 50% chance of success
            self._write_event("verification", {
                "success": 1,
                "attempts": self.attempts + 1,
            })
            self.output["BPM1_in"].add({})
        else:
            self.attempts += 1
            self.hold_in("processing", 10.0)

    def deltint(self):
        if self.phase == "processing":
            pass
        else:
            self.passivate("idle")

    def exit(self):
        pass