import json
import random
import time
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class PV(Atomic):
    """Performs password verification with a 10-second delay per attempt. Retries until success (50% chance per attempt)."""

    def __init__(self, name: str, parent: Coupled | None, processing_delay: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay = processing_delay
        
        # Ports
        self.add_in_port(Port(dict, "verification_in"))
        self.add_out_port(Port(dict, "success_out"))
        
        # State
        self.attempts = 0
        self.payload_to_send = None

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
        self.attempts = 0
        self.payload_to_send = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # If we are busy processing (or waiting to output), we continue processing.
        # However, PV logic implies it handles one verification flow at a time based on the input.
        # If we receive input while IDLE, we start processing.
        # If we receive input while busy, the requirements don't specify buffering for PV specifically,
        # but the general architecture implies sequential processing. 
        # Given the atomic nature and the "retries until success" logic, it processes one request.
        
        if self.phase == "IDLE":
            # Read input. We expect one input to trigger the sequence.
            # The input structure is {'timestamp': float, 'pass': int, 'fail': int} from ANV.
            # However, PV logic is driven by internal retries. The input just triggers the start.
            for _ in self.input["verification_in"].values:
                self.attempts = 1
                # Start the first attempt
                self.hold_in("PROCESSING", self.processing_delay)
                break
        else:
            # If busy, we just continue the current phase (subtract elapsed time)
            self.continuef(e)

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self.payload_to_send is not None:
            self.output["success_out"].add(dict(self.payload_to_send))

    def deltint(self):
        if self.phase == "PROCESSING":
            # An attempt has finished. Check success.
            # 50% chance of success.
            # random.random() returns [0.0, 1.0). < 0.5 is 50%.
            success = 1 if random.random() < 0.5 else 0
            
            if success == 1:
                # Success!
                # 1. Prepare external IO record
                self._write_verification_event(success=1, attempts=self.attempts)
                
                # 2. Prepare DEVS output payload
                # Structure: {'timestamp': float, 'attempts': int}
                self.payload_to_send = {
                    "timestamp": get_current_time(),
                    "attempts": self.attempts
                }
                
                # 3. Schedule output emission
                self.hold_in("OUTPUT_READY", 0.0)
            else:
                # Failure. Retry.
                self.attempts += 1
                # Schedule next attempt with delay
                self.hold_in("PROCESSING", self.processing_delay)
                
        elif self.phase == "OUTPUT_READY":
            # Output sent. Reset state and go IDLE.
            self.attempts = 0
            self.payload_to_send = None
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass