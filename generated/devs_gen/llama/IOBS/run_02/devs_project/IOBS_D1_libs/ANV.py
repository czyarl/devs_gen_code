"""Complete implementation for Atomic DEVS model ANV."""

import json
import random
import sys

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class ANV(Atomic):
    """Account Number Verifier: Randomly verifies account numbers."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "pass_request_out"))

    def initialize(self):
        self.passivate("WAITING")

    def deltext(self, e):
        for request in self.input["request_in"].values:
            self.output["pass_request_out"].add(dict(request))

            # Perform random verification
            if random.random() < 0.5:
                pass_fail = {"pass": 1, "fail": 0}
            else:
                pass_fail = {"pass": 0, "fail": 1}

            print(json.dumps({
                "time": get_current_time(),
                "model": "ANV",
                "event": "verification",
                "data": pass_fail,
            }), flush=True)

            self.hold_in("OUTPUT_READY", 0.0)

    def lambdaf(self):
        if self.phase != "OUTPUT_READY":
            return

        self.passivate("WAITING")

    def deltint(self):
        pass

    def exit(self):
        pass