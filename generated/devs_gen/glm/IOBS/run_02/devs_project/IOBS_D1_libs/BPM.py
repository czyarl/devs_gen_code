import json
import random
import time

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class BPM(Atomic):
    """BillPaymentManager: Receives successful verification, generates a bill amount after a delay, and forwards it."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Configuration
        self.processing_delay = 10.0
        
        # Ports
        self.add_in_port(Port(dict, "success_in"))
        self.add_out_port(Port(dict, "bill_out"))
        
        # Internal state
        self.bill_amount = None

    def initialize(self):
        # Initialize random seed as per requirements
        random.seed(time.time_ns())
        
        self.bill_amount = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        if self.phase == "BUSY":
            # While busy, ignore any subsequent inputs on 'success_in'
            self.continuef(e)
            return

        # Check for input on success_in
        if not self.input["success_in"].empty():
            # Consume the input (we don't need the content, just the trigger)
            _ = self.input["success_in"].get()
            
            # Transition to busy state and schedule internal transition
            self.hold_in("BUSY", self.processing_delay)
        else:
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "BUSY" and self.bill_amount is not None:
            # Construct payload dictionary
            payload = {"amount": self.bill_amount}
            self.output["bill_out"].add(payload)

    def deltint(self):
        if self.phase == "BUSY":
            # Generate random bill amount between 0 and 40
            self.bill_amount = random.randint(0, 40)
            
            # Write JSONL record to stdout
            current_time = get_current_time()
            record = {
                "time": current_time,
                "model": "BPM1",
                "event": "bill",
                "data": {"amount": self.bill_amount}
            }
            print(json.dumps(record), flush=True)
            
            # Return to idle state
            self.passivate("IDLE")

    def exit(self):
        pass