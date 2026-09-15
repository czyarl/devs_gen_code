"""TPM: TransactionProcessManager for IOBS."""

import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class TPM(Atomic):
    """TransactionProcessManager: Processes bill payments, updates balance and count."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.add_in_port(Port(dict, "bill_in"))
        
        # Internal State
        self.balance = 3000
        self.count = 0
        self.queue = []
        self.current_amount = None

    def initialize(self):
        self.balance = 3000
        self.count = 0
        self.queue = []
        self.current_amount = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # Read incoming bill amounts
        for packet in self.input["bill_in"].values:
            amount = packet.get("amount")
            if amount is not None:
                self.queue.append(amount)

        # State transition logic
        if self.phase == "IDLE":
            if self.queue:
                # Start processing immediately if idle
                self.current_amount = self.queue.pop(0)
                self.hold_in("PROCESSING", 10.0)
            else:
                self.passivate("IDLE")
        elif self.phase == "PROCESSING":
            # Preserve remaining time for current processing
            # New items are just buffered
            self.hold_in("PROCESSING", max(0.0, self.ta() - e))

    def lambdaf(self):
        # This model has no DEVS output ports
        pass

    def deltint(self):
        # Processing delay finished
        if self.phase == "PROCESSING" and self.current_amount is not None:
            # Update balance and count
            self.balance -= self.current_amount
            self.count += 1
            
            # Emit external IO event (stdout)
            current_time = get_current_time()
            
            record = {
                "time": current_time,
                "model": self.name,
                "event": "transaction",
                "data": {
                    "remaining": self.balance,
                    "count": self.count
                }
            }
            print(json.dumps(record), flush=True)

            # Reset current item
            self.current_amount = None

            # Check queue for next item
            if self.queue:
                self.current_amount = self.queue.pop(0)
                self.hold_in("PROCESSING", 10.0)
            else:
                self.passivate("IDLE")

    def exit(self):
        pass