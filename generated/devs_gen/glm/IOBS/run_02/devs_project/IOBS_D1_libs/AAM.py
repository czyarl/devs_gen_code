import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class AAM(Atomic):
    """AccountAccessManager: Buffers login requests and processes them sequentially."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "account_out"))
        
        # Internal State
        self.queue = []
        self.processing_delay = 10.0
        self.current_request = None
        self.payload_to_send = None

    def initialize(self):
        self.queue = []
        self.current_request = None
        self.payload_to_send = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # If we are currently processing, we must preserve the remaining time
        if self.phase == "PROCESSING":
            self.continuef(e)
        
        # Buffer incoming requests
        for request in self.input["request_in"].values:
            self.queue.append(request)
            
            # If idle, start processing immediately
            if self.phase == "IDLE":
                self._start_processing()

    def _start_processing(self):
        if not self.queue:
            self.passivate("IDLE")
            return

        self.current_request = self.queue.pop(0)
        self.hold_in("PROCESSING", self.processing_delay)

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self.payload_to_send is not None:
            # Only send DEVS output if it's a valid login (account_generated)
            # For logout, payload_to_send is None or we don't send to port
            if self.payload_to_send is not None:
                self.output["account_out"].add(self.payload_to_send)

    def deltint(self):
        if self.phase == "PROCESSING":
            # Processing delay finished. Determine event type and write to stdout.
            req = self.current_request
            valid = req.get("valid", 0)
            invalid = req.get("invalid", 0)
            
            current_time = get_current_time()
            
            if valid == 1 and invalid == 0:
                # Valid login
                record = {
                    "time": current_time,
                    "model": "AAM1",
                    "event": "account_generated",
                    "data": {}
                }
                print(json.dumps(record), flush=True)
                self.payload_to_send = {}
                self.hold_in("OUTPUT_READY", 0.0)
                
            elif valid == 1 and invalid == 1:
                # Invalid login
                record = {
                    "time": current_time,
                    "model": "AAM1",
                    "event": "logout",
                    "data": {}
                }
                print(json.dumps(record), flush=True)
                # No DEVS output for logout
                self.payload_to_send = None
                # Transition to check next item immediately (sigma=0)
                self.hold_in("OUTPUT_READY", 0.0)
            else:
                # Undefined state based on contract, passivate or handle gracefully
                self.passivate("IDLE")

        elif self.phase == "OUTPUT_READY":
            # Output phase finished. Check queue for next item.
            self.current_request = None
            self.payload_to_send = None
            
            if self.queue:
                self._start_processing()
            else:
                self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass