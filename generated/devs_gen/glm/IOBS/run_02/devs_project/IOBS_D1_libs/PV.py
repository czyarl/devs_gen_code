import json
import random
import time
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class PV(Atomic):
    """Receives verifications from ANV, waits 10 seconds per attempt, and performs random password checks (50% success per attempt) until success. Forwards to BPM upon success. Emits a 'verification' event with success status and attempt count."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.add_in_port(Port(dict, "verification_in"))
        self.add_out_port(Port(dict, "success_out"))
        
        # Internal state
        self.attempts = 0
        self.processing_delay = 10.0

    def _write_verification_event(self, success: int, attempts: int) -> None:
        """Writes the 'verification' event to stdout."""
        record = {
            "time": get_current_time(),
            "model": "PV1",
            "event": "verification",
            "data": {
                "success": success,
                "attempts": attempts
            }
        }
        print(json.dumps(record), flush=True)

    def initialize(self):
        self.passivate("IDLE")

    def deltext(self, e: float):
        # Receive verification from ANV
        received = False
        for _ in self.input["verification_in"].values:
            received = True
        
        if received:
            # Start processing: reset attempts, wait for processing delay
            self.attempts = 0
            self.hold_in("PROCESSING", self.processing_delay)
        else:
            self.continuef(e)

    def lambdaf(self):
        # Emit DEVS output when success is achieved
        if self.phase == "OUTPUT_READY":
            # Payload structure is not strictly defined in contract for success_out, 
            # but usually empty dict or similar is used for signal.
            self.output["success_out"].add({})

    def deltint(self):
        if self.phase == "PROCESSING":
            # Processing delay finished, perform random check
            self.attempts += 1
            
            # Random password check: 50% success per attempt
            # Use random.random() < 0.5 for success
            success = 1 if random.random() < 0.5 else 0
            
            if success:
                # Success: Emit event and schedule output
                self._write_verification_event(1, self.attempts)
                self.hold_in("OUTPUT_READY", 0.0)
            else:
                # Fail: Retry immediately (wait another 10s)
                # Note: The requirement says "waits 10 seconds per attempt".
                # So we loop back to PROCESSING.
                self.hold_in("PROCESSING", self.processing_delay)
                
        elif self.phase == "OUTPUT_READY":
            # Output sent, go back to idle
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass