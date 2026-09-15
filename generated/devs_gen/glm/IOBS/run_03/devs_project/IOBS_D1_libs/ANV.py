import json
import random
import time
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ANV(Atomic):
    """Account Number Verifier: Buffers requests, processes with fixed delay, and verifies randomly."""

    def __init__(self, name: str, parent: Coupled | None, processing_delay: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay = processing_delay
        
        # Ports
        self.add_in_port(Port(dict, "account_in"))
        self.add_out_port(Port(dict, "verification_out"))
        
        # State variables
        self.current_request = None
        self.waiting_request = None
        self.verification_result = None  # Stores {'pass': int, 'fail': int}

    def _write_verification_event(self, result: dict) -> None:
        """Emits the 'verification' event to stdout."""
        record = {
            "time": get_current_time(),
            "model": self.name,
            "event": "verification",
            "data": result
        }
        print(json.dumps(record), flush=True)

    def initialize(self):
        # Seed random number generator as per requirements
        random.seed(time.time_ns())
        
        self.current_request = None
        self.waiting_request = None
        self.verification_result = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        """Handle incoming account requests."""
        is_busy = self.phase == "PROCESSING"
        
        if is_busy:
            # If currently processing, reduce the remaining time
            self.continuef(e)

        # Buffer incoming requests
        for request in self.input["account_in"].values:
            if self.current_request is None:
                # Start processing immediately if idle
                self.current_request = request
                self.hold_in("PROCESSING", self.processing_delay)
            elif self.waiting_request is None:
                # Buffer if busy but buffer is empty
                self.waiting_request = request
            # Else: Drop request if buffer is full (implicit in "Buffers incoming requests ... if busy" implies capacity, usually 1 in these examples)

    def lambdaf(self):
        """Emit DEVS output if verification passed."""
        if self.phase == "OUTPUT_READY" and self.verification_result:
            if self.verification_result.get('pass') == 1:
                # Construct payload for verification_out
                # Contract: {'timestamp': float, 'pass': int, 'fail': int}
                payload = {
                    "timestamp": get_current_time(),
                    "pass": 1,
                    "fail": 0
                }
                self.output["verification_out"].add(payload)

    def deltint(self):
        """Handle internal transitions."""
        if self.phase == "PROCESSING":
            # Processing delay completed. Determine outcome.
            # 50/50 distribution: 0.0 to 0.5 fail, 0.5 to 1.0 pass
            outcome = random.random()
            passed = 1 if outcome >= 0.5 else 0
            
            self.verification_result = {
                "pass": passed,
                "fail": 1 - passed
            }
            
            # Emit external IO event (stdout)
            self._write_verification_event(self.verification_result)
            
            # Move to output phase to handle DEVS port emission
            self.hold_in("OUTPUT_READY", 0.0)
            
        elif self.phase == "OUTPUT_READY":
            # Clear current request
            self.current_request = None
            self.verification_result = None
            
            # Check if there is a waiting request
            if self.waiting_request is not None:
                self.current_request = self.waiting_request
                self.waiting_request = None
                self.hold_in("PROCESSING", self.processing_delay)
            else:
                self.passivate("IDLE")
        else:
            # Should not happen, but safe fallback
            self.passivate("IDLE")

    def exit(self):
        pass