"""Implementation of the AAM model."""

import json

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class AAM(Atomic):
    """Account Access Manager model."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "valid_request_out"))
        self.add_out_port(Port(dict, "logout_out"))

    def initialize(self):
        self.passivate("IDLE")

    def deltext(self, e):
        for request in self.input["request_in"].values:
            valid = request["valid"]
            invalid = request["invalid"]

            if valid == 1 and invalid == 0:
                self.output["valid_request_out"].add(request)
                print(json.dumps({
                    "time": get_current_time(),
                    "model": "AAM",
                    "event": "account_generated",
                    "data": {},
                }), flush=True)
            elif valid == 1 and invalid == 1:
                print(json.dumps({
                    "time": get_current_time(),
                    "model": "AAM",
                    "event": "logout",
                    "data": {},
                }), flush=True)
                # No need to forward to ANV
            else:
                # Invalid request, do nothing
                pass

    def lambdaf(self):
        pass

    def deltint(self):
        self.passivate("IDLE")

    def exit(self):
        pass