"""TPM1: Processes transaction bills by deducting the amount from the initial balance of 3000, tracking the number of completed transactions, and emitting a final state update to stdout when a bill is received."""

import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class TPM1(Atomic):
    """Transaction Process Manager model for IOBS system."""

    def __init__(self, name: str, parent: Coupled | None, initial_balance: int = 3000):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "bill"))
        self.balance = initial_balance
        self.transaction_count = 0
        self.pending_bill = None

    def initialize(self):
        self.balance = 3000
        self.transaction_count = 0
        self.pending_bill = None
        self.passivate("IDLE")

    def deltext(self, e):
        for bill in self.input["bill"].values:
            self.pending_bill = bill
            # Schedule processing delay of 10 seconds
            self.hold_in("PROCESSING", 10.0)
        if self.phase == "IDLE":
            self.passivate("IDLE")

    def lambdaf(self):
        # This model does not emit DEVS port outputs
        pass

    def deltint(self):
        if self.phase == "PROCESSING":
            # Process the bill
            bill_amount = self.pending_bill["amount"]
            self.balance = max(0, self.balance - bill_amount)
            self.transaction_count += 1

            # Emit final state update to stdout
            record = {
                "time": get_current_time(),
                "model": "TPM1",
                "event": "transaction",
                "data": {
                    "remaining": self.balance,
                    "count": self.transaction_count
                }
            }
            print(json.dumps(record), flush=True)

            # Clear the pending bill and return to idle
            self.pending_bill = None
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass