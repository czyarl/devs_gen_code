import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class TPM(Atomic):
    """TransactionProcessManager: Maintains balance and processes bill payments."""

    def __init__(self, name: str, parent: Coupled | None, initial_balance: int, processing_delay: float):
        super().__init__(name)
        self.parent = parent
        self.initial_balance = initial_balance
        self.processing_delay = processing_delay

        # Ports
        self.add_in_port(Port(dict, "bill_in"))
        self.add_out_port(Port(dict, "balance_out"))

        # State variables
        self.balance = initial_balance
        self.count = 0
        self.queue = []
        self.current_bill = None
        self.payload_to_send = None

    def _write_event(self, remaining: int, count: int) -> None:
        """Writes the 'transaction' event record to stdout."""
        print(json.dumps({
            "time": get_current_time(),
            "model": self.name,
            "event": "transaction",
            "data": {
                "remaining": remaining,
                "count": count
            }
        }), flush=True)

    def initialize(self):
        """Initialize state and emit initial balance."""
        self.balance = self.initial_balance
        self.count = 0
        self.queue = []
        self.current_bill = None
        self.payload_to_send = None

        # Emit initial balance via port immediately (requires 0.0 delay phase)
        self.payload_to_send = {"remaining": self.balance}
        self.hold_in("INITIAL_OUTPUT", 0.0)

    def deltext(self, e: float):
        """Handle incoming bill payments."""
        was_processing = self.phase == "PROCESSING"
        
        if was_processing:
            self.continuef(e)

        for bill in self.input["bill_in"].values:
            if self.current_bill is None:
                # If idle, start processing immediately
                self.current_bill = bill
                self.hold_in("PROCESSING", self.processing_delay)
            else:
                # If busy, add to queue
                self.queue.append(bill)

    def lambdaf(self):
        """Emit DEVS output based on current phase."""
        if self.phase == "INITIAL_OUTPUT":
            if self.payload_to_send is not None:
                self.output["balance_out"].add(dict(self.payload_to_send))
        elif self.phase == "OUTPUT_READY":
            if self.payload_to_send is not None:
                self.output["balance_out"].add(dict(self.payload_to_send))

    def deltint(self):
        """Handle internal transitions."""
        if self.phase == "INITIAL_OUTPUT":
            # After emitting initial balance, passivate and wait for bills
            self.payload_to_send = None
            self.passivate("IDLE")

        elif self.phase == "PROCESSING":
            # Processing delay expired: update balance and count
            amount = self.current_bill.get("amount", 0)
            self.balance -= amount
            self.count += 1
            
            # Write external IO event
            self._write_event(self.balance, self.count)

            # Prepare DEVS output
            self.payload_to_send = {"remaining": self.balance}
            
            # Schedule output emission
            self.hold_in("OUTPUT_READY", 0.0)

        elif self.phase == "OUTPUT_READY":
            # Output emitted, clear current bill
            self.current_bill = None
            self.payload_to_send = None

            # Check queue for next bill
            if self.queue:
                next_bill = self.queue.pop(0)
                self.current_bill = next_bill
                self.hold_in("PROCESSING", self.processing_delay)
            else:
                self.passivate("IDLE")
        
        else:
            self.passivate("IDLE")

    def exit(self):
        pass