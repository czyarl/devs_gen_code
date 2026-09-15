"""Atomic DEVS model for ANV1 (Account Number Verifier)."""

import json
import random
import time
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ANV1(Atomic):
    """Verifies account numbers with a fixed processing delay and random outcome."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.add_in_port(Port(dict, "account_in"))
        self.add_out_port(Port(dict, "verification_out"))
        
        # Constants
        self.PROCESSING_DELAY = 10.0
        
        # Internal State
        self.queue = deque()
        self.current_request = None
        self.verification_result = None
        self.pass_count = 0
        self.fail_count = 0

    def _log_verification(self, pass_val: int, fail_val: int):
        """Emits the JSONL verification event to stdout."""
        record = {
            "time": get_current_time(),
            "model": "ANV1",
            "event": "verification",
            "data": {
                "pass": pass_val,
                "fail": fail_val
            }
        }
        print(json.dumps(record), flush=True)

    def initialize(self):
        """Initializes the model state."""
        self.queue.clear()
        self.current_request = None
        self.verification_result = None
        self.pass_count = 0
        self.fail_count = 0
        self.passivate("IDLE")

    def deltext(self, e: float):
        """Handles external input (account data)."""
        # If we were processing, continue processing, adjusting sigma
        if self.phase == "PROCESSING":
            self.continuef(e)

        # Buffer incoming requests
        for request in self.input["account_in"].values:
            if self.current_request is None:
                # If idle, start processing immediately
                self.current_request = request
                self.hold_in("PROCESSING", self.PROCESSING_DELAY)
            else:
                # If busy, enqueue
                self.queue.append(request)

    def lambdaf(self):
        """Emits output when the internal transition triggers."""
        if self.phase == "OUTPUT_READY" and self.verification_result is not None:
            # Only forward to PV1 if verification passed
            if self.verification_result["pass"] == 1:
                self.output["verification_out"].add(dict(self.verification_result))

    def deltint(self):
        """Handles internal transitions."""
        if self.phase == "PROCESSING":
            # Processing delay is complete. Perform verification.
            # 50% chance pass, 50% chance fail
            if random.random() < 0.5:
                self.pass_count += 1
                self.verification_result = {"pass": 1, "fail": 0}
                self._log_verification(1, 0)
            else:
                self.fail_count += 1
                self.verification_result = {"pass": 0, "fail": 1}
                self._log_verification(0, 1)
            
            # Schedule output immediately
            self.hold_in("OUTPUT_READY", 0.0)

        elif self.phase == "OUTPUT_READY":
            # Output phase complete. Clear current request.
            self.current_request = None
            self.verification_result = None
            
            # Check queue for next request
            if self.queue:
                next_request = self.queue.popleft()
                self.current_request = next_request
                self.hold_in("PROCESSING", self.PROCESSING_DELAY)
            else:
                self.passivate("IDLE")

        else:
            # Should not happen if logic is correct, but passivate to be safe
            self.passivate("IDLE")

    def exit(self):
        """Cleanup on simulation exit."""
        pass