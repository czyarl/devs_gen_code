"""BPM1: Bill Payment Manager - Generates random bill amount after verification."""

import random
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class BPM1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "verification"))
        self.add_out_port(Port(dict, "bill"))
        self.verification_data = None
        self.bill_amount = None

    def initialize(self):
        self.verification_data = None
        self.bill_amount = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return
        for packet in self.input["verification"].values:
            # Store verification data
            self.verification_data = dict(packet)
            # Schedule processing delay of 10 seconds
            self.hold_in("PROCESSING", 10.0)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.verification_data is not None:
            # Generate random bill amount between 0 and 40
            self.bill_amount = random.randint(0, 40)
            # Emit bill amount on output port
            self.output["bill"].add({"amount": self.bill_amount})

    def deltint(self):
        # Clear state after processing
        self.verification_data = None
        self.bill_amount = None
        self.passivate("IDLE")

    def exit(self):
        pass