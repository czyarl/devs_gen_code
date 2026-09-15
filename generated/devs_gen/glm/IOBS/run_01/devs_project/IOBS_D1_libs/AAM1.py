"""Atomic model AAM1: Processes login requests with a fixed 10-second delay."""

import json
import sys

from xdevs.models import Atomic, Coupled, Port

# Import the utility for getting simulation time if needed, though typically
# xDEVS Atomic models rely on the simulator's clock via `self.phase` and `sigma`.
# The prompt mentions: "If the contract needs the current simulation time, import get_current_time...".
# However, for outputting the time in JSONL, we usually need the absolute time.
# In xDEVS, `self.phase` and `sigma` manage internal timing. The absolute time
# is often passed or calculated. The prompt provides `get_current_time`.
from devs_project.devs_utils.devs_context import get_current_time


class AAM1(Atomic):
    """
    Account Access Manager.
    Processes login requests with a fixed 10-second delay.
    Maintains an unbounded FIFO queue.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Define Ports
        # Input: Receives login requests from InputReader1
        self.add_in_port(Port(dict, "request_in"))
        # Output: Forwards valid account data to ANV1
        self.add_out_port(Port(dict, "account_out"))

        # Internal State
        self.processing_delay = 10.0
        self.queue = []
        self.current_request = None

    def initialize(self):
        """Initialize state variables and passivate waiting for input."""
        self.queue = []
        self.current_request = None
        self.passivate("IDLE")

    def _start_processing(self):
        """Pop the next request from the queue and start processing."""
        if self.queue:
            self.current_request = self.queue.pop(0)
            self.hold_in("PROCESSING", self.processing_delay)
        else:
            self.passivate("IDLE")

    def deltext(self, e: float):
        """
        Handle external input (login requests).
        Queue them if busy, or start processing immediately if idle.
        """
        # Check if we were currently processing a request
        was_processing = self.phase == "PROCESSING"
        
        # Calculate remaining time for the current request if we were processing
        # We must preserve the timer for the current request.
        remaining_time = 0.0
        if was_processing:
            remaining_time = max(0.0, self.ta() - e)

        # Read all incoming requests and add to the queue
        for packet in self.input["request_in"].values:
            # Ensure we store a copy to avoid reference issues if the source mutates
            self.queue.append(dict(packet))

        # State transition logic
        if not was_processing:
            # If we were idle, and we have requests, start processing the first one
            if self.queue:
                self._start_processing()
            else:
                # Still idle
                self.passivate("IDLE")
        else:
            # If we were processing, we must continue processing the current request
            # with the remaining time. New requests are just queued.
            self.hold_in("PROCESSING", remaining_time)

    def lambdaf(self):
        """
        Output function.
        Emits DEVS output to 'account_out' and writes JSONL to stdout.
        """
        if self.phase == "PROCESSING" and self.current_request is not None:
            req = self.current_request
            valid = req.get("valid", 0)
            invalid = req.get("invalid", 0)

            # Logic based on flags
            if valid == 1 and invalid == 0:
                # Valid login: Forward to ANV1 and emit 'account_generated'
                self.output["account_out"].add(dict(req))
                
                # External IO: stdout JSONL
                record = {
                    "time": get_current_time(),
                    "model": "AAM1",
                    "event": "account_generated",
                    "data": {}
                }
                print(json.dumps(record), flush=True)

            elif valid == 1 and invalid == 1:
                # Invalid login: Emit 'logout', no forwarding
                record = {
                    "time": get_current_time(),
                    "model": "AAM1",
                    "event": "logout",
                    "data": {}
                }
                print(json.dumps(record), flush=True)

    def deltint(self):
        """
        Internal transition.
        Called after processing delay expires.
        Clears current request and starts the next one if any.
        """
        self.current_request = None
        
        # Check if there are more requests in the queue
        if self.queue:
            self._start_processing()
        else:
            self.passivate("IDLE")

    def exit(self):
        """Cleanup method."""
        pass