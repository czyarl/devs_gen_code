"""Atomic DEVS model: ANV."""

import json
import random

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class ANV(Atomic):
    """Perform random verification and send the result to PV."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "verification_out"))

    def initialize(self):
        self.passivate("idle")

    def deltext(self, e):
        for request in self.input["request_in"].values:
            self.request = request
            self.hold_in("processing", 10.0)

    def lambdaf(self):
        if self.phase != "processing":
            return

        # Perform random verification
        verification_result = random.choice([{"pass": 1, "fail": 0}, {"pass": 0, "fail": 1}])

        # Send verification result
        self.output["verification_out"].add(verification_result)

        print(json.dumps({
            "time": get_current_time(),
            "model": self.name,
            "event": "verification",
            "data": verification_result,
        }), flush=True)

        self.passivate("idle")

    def deltint(self):
        pass

    def exit(self):
        pass