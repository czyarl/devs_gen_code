import json
import random
import time
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ANV(Atomic):
    """
    Atomic DEVS model for Account Number Verification (ANV).
    Receives account dictionaries, processes them with a fixed delay,
    performs a random verification check, and forwards passed accounts.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Define ports as per locked contract
        self.add_in_port(Port(dict, "account_in"))
        self.add_out_port(Port(dict, "verification_out"))

        # Internal state
        self.queue = []
        self.current_account = None
        self.verification_result = None  # Stores {"pass": 0|1, "fail": 0|1}
        self.processing_delay = 10.0

    def initialize(self):
        """Initialize the model state."""
        self.queue = []
        self.current_account = None
        self.verification_result = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        """Handle external input events."""
        # If we were processing, continue processing and reduce remaining time
        if self.phase == "PROCESSING":
            self.continuef(e)

        # Read all incoming account dictionaries
        for account in self.input["account_in"].values:
            if self.current_account is None:
                # If idle, start processing immediately
                self.current_account = account
                self.hold_in("PROCESSING", self.processing_delay)
            else:
                # If busy, queue the request
                self.queue.append(account)

    def lambdaf(self):
        """Generate output when the internal event triggers."""
        if self.phase == "OUTPUT_READY":
            # If verification passed, forward the account payload
            if self.verification_result and self.verification_result.get("pass") == 1:
                self.output["verification_out"].add(self.current_account)

            # Emit the verification event to stdout (independent obligation)
            # The contract requires this event for both pass and fail cases.
            event_record = {
                "time": get_current_time(),
                "model": "ANV1",
                "event": "verification",
                "data": self.verification_result
            }
            print(json.dumps(event_record), flush=True)

    def deltint(self):
        """Handle internal state transitions."""
        if self.phase == "PROCESSING":
            # Processing delay finished. Determine verification result.
            # 50% chance pass, 50% chance fail
            is_pass = random.choice([True, False])

            self.verification_result = {
                "pass": 1 if is_pass else 0,
                "fail": 0 if is_pass else 1
            }

            # Schedule output phase immediately (sigma=0)
            self.hold_in("OUTPUT_READY", 0.0)

        elif self.phase == "OUTPUT_READY":
            # Output phase finished. Clean up current request.
            self.current_account = None
            self.verification_result = None

            # Check if there are queued requests
            if self.queue:
                self.current_account = self.queue.pop(0)
                self.hold_in("PROCESSING", self.processing_delay)
            else:
                self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        """Cleanup on simulation exit."""
        pass