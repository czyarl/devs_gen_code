"""Implementation of the Bill Payment Manager (BPM) atomic model."""

import json
import random
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class BPM(Atomic):
    """Bill Payment Manager (BPM) atomic model.

    Receives successful password verification, generates a random bill amount between 0 and 40,
    ensures it does not exceed the remaining account balance, and forwards the bill amount to TPM.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "bill_out"))
        self.account_balance = 3000  # Initial balance
        self.transaction_count = 0

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "model": self.name,
            "event": event,
            "data": payload,
        }), flush=True)

    def initialize(self):
        self.passivate("IDLE")

    def deltext(self, e):
        for packet in self.input["request_in"].values:
            self.hold_in("PROCESSING", 10.0)  # 10 seconds processing delay

    def lambdaf(self):
        if self.phase == "PROCESSING":
            for packet in self.input["request_in"].values:
                success = packet["success"]
                attempts = packet["attempts"]
                if success == 1:
                    bill_amount = self.generate_bill_amount()
                    self._write_event("bill", {"amount": bill_amount})
                    self.output["bill_out"].add({"time": get_current_time(), "amount": bill_amount})
                self.passivate("IDLE")

    def deltint(self):
        pass

    def exit(self):
        pass

    def generate_bill_amount(self) -> int:
        """Generate a random bill amount between 0 and 40 that does not exceed the remaining account balance."""
        while True:
            bill_amount = random.randint(0, 40)
            if bill_amount <= self.account_balance:
                self.account_balance -= bill_amount
                self.transaction_count += 1
                return bill_amount