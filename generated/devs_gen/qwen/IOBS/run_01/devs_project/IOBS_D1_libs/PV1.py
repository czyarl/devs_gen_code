"""PV1: Password Verifier model implementing random password attempts with 50% success chance."""

import random
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class PV1(Atomic):
    """Password verifier with 50% success chance per attempt."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "verification"))
        self.add_out_port(Port(dict, "verification"))
        self.current_request = None
        self.attempts = 0

    def initialize(self):
        self.current_request = None
        self.attempts = 0
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        for item in self.input["verification"].values:
            self.current_request = dict(item)
            self.attempts = 0
            self.hold_in("PROCESSING", 0.0)  # Start immediately
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.current_request is not None:
            # Simulate password attempts until success (50% chance)
            while True:
                self.attempts += 1
                if random.random() < 0.5:  # 50% chance of success
                    result = {"success": 1, "attempts": self.attempts}
                    self.output["verification"].add(result)
                    break

    def deltint(self):
        if self.phase == "PROCESSING":
            # Schedule the output after 10 seconds processing delay
            self.hold_in("OUTPUT_READY", 10.0)
        elif self.phase == "OUTPUT_READY":
            # Clear the current request and return to idle
            self.current_request = None
            self.attempts = 0
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass