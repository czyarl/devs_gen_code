"""Atomic DEVS model AAM1 implementation."""

import json
from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class AAM1(Atomic):
    """Account Access Manager 1.

    Receives login requests. Response depends on the validity of the request input.
    If valid=1 and invalid=0: Forward to ANV1.
    If valid=1 and invalid=1: Emit the required logout record and end
    processing for this request. Do not return it to the input reader or
    forward it to another entity. Logout is stdout-only observation, not
    a DEVS output port.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "input"))
        self.add_out_port(Port(dict, "ANV1_in"))
        self.add_out_port(Port(dict, "logout"))

    def initialize(self):
        self.passivate("idle")

    def deltext(self, e):
        for request in self.input["input"].values:
            self.output["ANV1_in"].add(dict(request))
            print(json.dumps({
                "time": get_current_time(),
                "model": "AAM1",
                "event": "account_generated",
                "data": {}
            }), flush=True)

        for _ in self.input["logout"].values:
            print(json.dumps({
                "time": get_current_time(),
                "model": "AAM1",
                "event": "logout",
                "data": {}
            }), flush=True)

        self.hold_in(self.phase, 0.0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def exit(self):
        pass