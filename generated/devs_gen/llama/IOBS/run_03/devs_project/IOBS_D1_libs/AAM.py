"""Complete pattern: AAM model."""

import json
import random

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class AAM(Atomic):
    """AAM model."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "account_generated_out"))
        self.add_out_port(Port(dict, "logout_out"))
        self.add_out_port(Port(dict, "valid_request_out"))

    def initialize(self):
        self.passivate("WAITING")

    def deltext(self, e):
        for request in self.input["request_in"].values:
            valid = request["valid"]
            invalid = request["invalid"]
            timestamp = request["timestamp"]
            if valid == 1 and invalid == 0:
                self.output["valid_request_out"].add({})
                self.hold_in("VALID_REQUEST", 10.0)
            elif valid == 1 and invalid == 1:
                self.output["logout_out"].add({})
                self.hold_in("INVALID_REQUEST", 10.0)

    def lambdaf(self):
        # Emit account_generated_out
        self.output["account_generated_out"].add({})
        pass

    def deltint(self):
        self.passivate("WAITING")

    def exit(self):
        pass