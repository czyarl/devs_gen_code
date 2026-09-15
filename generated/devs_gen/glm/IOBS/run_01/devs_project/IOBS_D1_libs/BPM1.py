"""Atomic model for BPM1 (BillPaymentManager)."""

import json
import random
import time
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class BPM1(Atomic):
    """Receives successful password verification, generates a bill amount, and forwards it."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.add_in_port(Port(dict, "password_success_in"))
        self.add_out_port(Port(dict, "bill_out"))
        
        # State variables
        self.current_request = None
        self.queue = []
        self.bill_amount = None
        
        # Constants
        self.processing_delay = 10.0

    def initialize(self):
        """Initialize state and wait for input."""
        # Seed random number generator as per requirements
        # Using system time to set the seed
        seed_val = time.time_ns()
        random.seed(seed_val)
        
        self.current_request = None
        self.queue = []
        self.bill_amount = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        """Handle incoming password success messages."""
        # If we were processing, reduce the time remaining
        if self.phase == "PROCESSING":
            self.continuef(e)
        
        # Process all incoming messages
        for msg in self.input["password_success_in"].values:
            if self.current_request is None:
                # Start processing this request immediately
                self.current_request = msg
                self.hold_in("PROCESSING", self.processing_delay)
            else:
                # Retain in internal FIFO queue
                self.queue.append(msg)

    def lambdaf(self):
        """Emit the generated bill amount."""
        if self.phase == "OUTPUT_READY" and self.bill_amount is not None:
            # Send to TPM1
            self.output["bill_out"].add({"amount": self.bill_amount})

    def deltint(self):
        """Handle internal transitions: processing complete or output done."""
        if self.phase == "PROCESSING":
            # Processing delay expired, generate bill amount
            # Random integer between 0 and 40 inclusive
            self.bill_amount = random.randint(0, 40)
            
            # Emit JSONL record to stdout
            record = {
                "time": get_current_time(),
                "model": "BPM1",
                "event": "bill",
                "data": {"amount": self.bill_amount}
            }
            print(json.dumps(record), flush=True)
            
            # Schedule output immediately
            self.hold_in("OUTPUT_READY", 0.0)
            
        elif self.phase == "OUTPUT_READY":
            # Output sent, check for next item
            self.current_request = None
            self.bill_amount = None
            
            if self.queue:
                # Process next item in queue
                self.current_request = self.queue.pop(0)
                self.hold_in("PROCESSING", self.processing_delay)
            else:
                # Return to idle
                self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        """Cleanup on simulation exit."""
        pass