"""TPM: Transaction Process Manager"""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class TPM(Atomic):
    """TPM: Transaction Process Manager"""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "bill_in"))
        self.balance = 3000
        self.transaction_count = 0

    def initialize(self):
        self.passivate("IDLE")

    def deltext(self, e):
        for packet in self.input["bill_in"].values:
            self.balance -= packet["amount"]
            self.transaction_count += 1
            self._write_event("transaction", {
                "remaining": self.balance,
                "count": self.transaction_count,
            })
            self.passivate("IDLE")

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "model": "TPM",
            "event": event,
            "data": payload,
        }), flush=True)