"""ANV1: Account Number Verifier model implementing the locked contract."""

import json
import random
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ANV1(Atomic):
    """Account Number Verifier model."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "account_in"))
        self.add_out_port(Port(dict, "verification_out"))
        self.account = None
        self.payload_to_send = None

    def initialize(self):
        self.account = None
        self.payload_to_send = None
        self.passivate("IDLE")

    def deltext(self, e):
        for account in self.input["account_in"].values:
            self.account = account

        if self.phase == "IDLE" and self.account is not None:
            # Prepare the verification result immediately
            self.payload_to_send = {
                "pass": 1 if random.random() < 0.5 else 0,
                "fail": 0 if random.random() < 0.5 else 1
            }
            # Schedule zero-delay output
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase != "IDLE":
            self.continuef(e)

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self.payload_to_send is not None:
            # Emit the verification result
            self.output["verification_out"].add(self.payload_to_send)

            # Log the event to stdout
            print(json.dumps({
                "time": get_current_time(),
                "model": self.name,
                "event": "verification",
                "data": self.payload_to_send,
            }), flush=True)

    def deltint(self):
        if self.phase == "OUTPUT_READY":
            self.payload_to_send = None
            self.account = None
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass