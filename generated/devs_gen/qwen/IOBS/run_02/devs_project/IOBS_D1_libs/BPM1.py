"""BPM1: Bill Payment Manager model implementation."""

import random
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class BPM1(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "verification_in"))
        self.add_out_port(Port(dict, "bill_out"))
        
        # Internal state
        self.balance = 3000
        self.transaction_count = 0
        self.pending_bill = None
        self.received_verification = False

    def initialize(self):
        # Initialize internal state
        self.balance = 3000
        self.transaction_count = 0
        self.pending_bill = None
        self.received_verification = False
        # Wait for verification signal
        self.passivate("WAITING")

    def deltext(self, e):
        if self.phase == "WAITING":
            # Receive verification signal from PV1
            for verification in self.input["verification_in"].values:
                self.received_verification = True
                # Generate random bill amount between 0 and 40
                bill_amount = random.randint(0, 40)
                # Ensure bill amount doesn't exceed balance (though contract says balance is always sufficient)
                bill_amount = min(bill_amount, self.balance)
                # Store the bill amount for later emission
                self.pending_bill = {"amount": bill_amount}
                # Schedule output at t+10 seconds
                self.hold_in("OUTPUT_READY", 10.0)
                return
        elif self.phase == "OUTPUT_READY":
            # This shouldn't happen as we're already scheduled to output
            self.continuef(e)
            return
        else:
            # Unexpected phase, just continue
            self.continuef(e)

    def lambdaf(self):
        # Emit the bill amount when we're in OUTPUT_READY phase
        if self.phase == "OUTPUT_READY" and self.pending_bill is not None:
            self.output["bill_out"].add(self.pending_bill)
            # Update transaction count
            self.transaction_count += 1
            # Update balance (though not required by contract for output)
            # self.balance -= self.pending_bill["amount"]

    def deltint(self):
        if self.phase == "OUTPUT_READY":
            # Clear the pending bill and go back to waiting
            self.pending_bill = None
            self.passivate("WAITING")
        else:
            # For other phases, just passivate
            self.passivate("WAITING")

    def exit(self):
        pass