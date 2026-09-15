"""TPM1 Atomic Model Implementation"""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class TPM1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "input"))
        self.add_out_port(Port(dict, "output"))
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
        for item in self.input["input"].values:
            amount = item["amount"]
            self.balance -= amount
            self.transaction_count += 1
            self._write_event("transaction", {
                "remaining": self.balance,
                "count": self.transaction_count,
            })
            self.passivate("IDLE")

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def exit(self):
        pass