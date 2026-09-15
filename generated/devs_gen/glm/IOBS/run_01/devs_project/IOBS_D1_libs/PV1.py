"""Atomic DEVS model PV1 for Password Verification."""

import json
import random
import time
from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class PV1(Atomic):
    """Verifies passwords based on verification status received from ANV1."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.add_in_port(Port(dict, "verification_in"))
        self.add_out_port(Port(dict, "password_success_out"))
        
        # Internal State
        self.attempts = 0
        self.processing_delay = 10.0
        self.check_success = False

    def initialize(self):
        # Seed random number generator as per requirements
        # Using system time to set the seed
        random.seed(time.time_ns())
        
        self.attempts = 0
        self.check_success = False
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "IDLE":
            # Check for input on verification_in
            # The input structure is {'pass': int, 'fail': int}
            for _ in self.input["verification_in"].values:
                # Start processing
                self.attempts = 1
                self.hold_in("BUSY", self.processing_delay)
                break
        else:
            # If busy, preserve remaining time
            self.continuef(e)

    def lambdaf(self):
        # This method is called when an internal transition occurs (sigma expires)
        if self.phase == "BUSY":
            # Perform the random check (50% success probability)
            # We perform the check here to determine if we output success or schedule another attempt.
            # The requirement says: "When an internal transition triggers... the model performs a random check... 
            # If the check fails... schedules another internal transition... Upon successful verification, the model emits..."
            
            success = random.choice([True, False])
            self.check_success = success
            
            if success:
                now = get_current_time()
                
                # External IO: stdout
                record = {
                    "time": now,
                    "model": "PV1",
                    "event": "verification",
                    "data": {
                        "success": 1,
                        "attempts": self.attempts
                    }
                }
                print(json.dumps(record), flush=True)
                
                # DEVS Output Port
                payload = {
                    "success": 1,
                    "attempts": self.attempts
                }
                self.output["password_success_out"].add(payload)

    def deltint(self):
        if self.phase == "BUSY":
            if self.check_success:
                # Success occurred. Return to IDLE.
                self.passivate("IDLE")
                self.attempts = 0
            else:
                # Failure occurred. Increment attempts and retry.
                self.attempts += 1
                self.hold_in("BUSY", self.processing_delay)

    def exit(self):
        pass