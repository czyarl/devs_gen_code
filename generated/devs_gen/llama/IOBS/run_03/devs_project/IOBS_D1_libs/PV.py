"""Complete implementation of the PV Atomic DEVS model."""

import json
import random
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class PV(Atomic):
    """PV model for password verification."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "verification_in"))
        self.add_out_port(Port(dict, "verification_out"))
        self.attempts = 0
        self.success = False

    def initialize(self):
        self.attempts = 0
        self.success = False
        self.passivate("IDLE")

    def deltext(self, e):
        for _ in self.input["verification_in"].values:
            self.hold_in("PROCESSING", 10.0)
            return
        self.continuef(e)

    def lambdaf(self):
        if self.phase != "PROCESSING":
            return
        self.attempts += 1
        if random.random() < 0.5:  # 50% chance of success
            self.success = True
            self.output["verification_out"].add({
                "success": 1,
                "attempts": self.attempts,
            })
            self.passivate("IDLE")
        else:
            self.hold_in("PROCESSING", 0.0)

    def deltint(self):
        pass

    def exit(self):
        pass