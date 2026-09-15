"""TPM1 tracks transaction count and balance, calculates remaining after deduction."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class TPM1(Atomic):
    """TPM1 tracks transaction count and balance, calculates remaining after deduction."""

    def __init__(self, name: str, parent: Coupled | None, processing_delay: float, initial_balance: int):
        super().__init__(name)
        self.parent = parent
        self.processing_delay = processing_delay
        self.initial_balance = initial_balance
        self.add_in_port(Port(dict, "amount_in"))
        self.balance = initial_balance
        self.transaction_count = 0
        self.pending_amount = None

    def initialize(self):
        self.balance = self.initial_balance
        self.transaction_count = 0
        self.pending_amount = None
        self.passivate("IDLE")

    def deltext(self, e):
        for packet in self.input["amount_in"].values:
            # Store the incoming amount for processing after delay
            self.pending_amount = packet["amount"]
            # Schedule processing after the fixed delay
            self.hold_in("PROCESSING", self.processing_delay)
        # If we're still in the same phase, adjust remaining time
        if self.phase == "IDLE":
            self.passivate("IDLE")
        else:
            # We are already processing, so no change needed
            pass

    def lambdaf(self):
        # No DEVS output ports
        pass

    def deltint(self):
        if self.phase == "PROCESSING":
            # Process the transaction
            amount = self.pending_amount
            # Deduct amount from balance (if valid)
            if amount > 0:
                self.balance -= amount
            self.transaction_count += 1
            # Emit transaction event to stdout
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
            # Prepare for next input
            self.pending_amount = None
            self.passivate("IDLE")
        else:
            # Unexpected phase transition
            self.passivate("IDLE")

    def exit(self):
        pass