"""TPM Atomic DEVS model implementation."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class TPM(Atomic):
    """TPM Atomic DEVS model."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "bill_in"))
        self.add_out_port(Port(dict, "transaction_out"))
        self.balance = 3000
        self.transaction_count = 0

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "model": self.name,
            "event": event,
            "data": payload,
        }), flush=True)

    def initialize(self):
        self.balance = 3000
        self.transaction_count = 0
        self.passivate("IDLE")

    def deltext(self, e):
        for packet in self.input["bill_in"].values:
            amount = packet["amount"]
            self.balance -= amount
            self.transaction_count += 1
            self._write_event("transaction", {
                "remaining": self.balance,
                "count": self.transaction_count,
            })
            self.hold_in("IDLE", 0.0)

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def exit(self):
        pass