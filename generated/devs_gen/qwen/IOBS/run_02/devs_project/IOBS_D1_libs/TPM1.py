"""TPM1: Transaction Process Manager model for IOBS system."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class TPM1(Atomic):
    """Transaction Process Manager model."""

    def __init__(self, name: str, parent: Coupled | None, initial_balance: int):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "bill_in"))
        self.add_out_port(Port(dict, "transaction_out"))
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.transaction_count = 0

    def initialize(self):
        self.balance = self.initial_balance
        self.transaction_count = 0
        self.passivate("IDLE")

    def deltext(self, e):
        for bill_data in self.input["bill_in"].values:
            amount = bill_data["amount"]
            self.balance -= amount
            self.transaction_count += 1
            # Schedule output event after 10 seconds processing delay
            self.hold_in("OUTPUT_READY", 10.0)
        # If no input was processed, remain idle
        if self.phase == "IDLE":
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "OUTPUT_READY":
            # Emit DEVS output port
            self.output["transaction_out"].add({
                "remaining": self.balance,
                "count": self.transaction_count
            })
            # Emit external IO record
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

    def deltint(self):
        if self.phase == "OUTPUT_READY":
            # Model terminates after processing one transaction
            self.passivate("TERMINATED")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass