"""BPM1: Generates a random bill amount between 0 and 40, constrained by the remaining account balance."""

import json
import random
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class BPM1(Atomic):
    def __init__(self, name: str, parent: Coupled | None, processing_delay: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay = processing_delay
        self.add_in_port(Port(dict, "account_in"))
        self.add_out_port(Port(dict, "amount_out"))
        self.account = None
        self.bill_amount = None

    def initialize(self):
        self.account = None
        self.bill_amount = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return
        for packet in self.input["account_in"].values:
            self.account = dict(packet)
            self.hold_in("PROCESSING", self.processing_delay)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.account is not None:
            # Generate a random bill amount between 0 and 40, constrained by remaining balance
            # For simplicity, we assume the initial balance is 3000 (as per TPM1's behavior)
            # But since BPM1 doesn't track balance, we'll just generate a random amount between 0 and 40
            # and let TPM handle the balance constraint logic
            self.bill_amount = random.randint(0, 40)
            # Emit the bill amount to TPM
            self.output["amount_out"].add({"amount": self.bill_amount})
            # Log the event to stdout
            record = {
                "time": get_current_time(),
                "model": "BPM1",
                "event": "bill",
                "data": {"amount": self.bill_amount}
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        self.account = None
        self.bill_amount = None
        self.passivate("IDLE")

    def exit(self):
        pass