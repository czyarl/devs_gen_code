import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class TPM1(Atomic):
    """TransactionProcessManager: Processes bill payments, updates balance, and tracks count."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Initialize ports
        self.add_in_port(Port(dict, "bill_in"))
        # No output ports as per locked contract

        # State variables
        self.balance = 3000
        self.transaction_count = 0
        self.current_bill = None
        self.waiting_bill = None
        self.processing_delay = 10.0

    def initialize(self):
        """Initialize state and passivate waiting for input."""
        self.balance = 3000
        self.transaction_count = 0
        self.current_bill = None
        self.waiting_bill = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        """Handle incoming bill amounts."""
        # If we were processing, we need to preserve the remaining time
        if self.phase == "PROCESSING":
            self.continuef(e)

        # Process all incoming bills
        for bill in self.input["bill_in"].values:
            if self.current_bill is None:
                # Start processing immediately
                self.current_bill = bill
                self.hold_in("PROCESSING", self.processing_delay)
            elif self.waiting_bill is None:
                # Queue the bill if we are busy but queue is empty
                self.waiting_bill = bill
            # If both are occupied, the request is dropped (implicit queue of size 1)

    def lambdaf(self):
        """This model has no output ports, so nothing is emitted here."""
        pass

    def deltint(self):
        """Handle internal transitions: processing completion."""
        if self.phase == "PROCESSING":
            # Update state
            amount = self.current_bill.get("amount", 0)
            self.balance -= amount
            self.transaction_count += 1

            # Emit external IO (JSONL to stdout)
            # Schema: {"time": <float>, "model": "TPM1", "event": "transaction", "data": {"remaining": <int>, "count": <positive int>}}
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

            # Clear current bill
            self.current_bill = None

            # Check if there is a waiting bill
            if self.waiting_bill is not None:
                self.current_bill = self.waiting_bill
                self.waiting_bill = None
                self.hold_in("PROCESSING", self.processing_delay)
            else:
                self.passivate("IDLE")
        else:
            # Should not happen in normal flow, but ensure passivation
            self.passivate("IDLE")

    def exit(self):
        """Cleanup if necessary."""
        pass