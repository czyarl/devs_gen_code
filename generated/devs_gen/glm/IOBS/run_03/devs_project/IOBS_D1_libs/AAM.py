import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time

class AAM(Atomic):
    """Account Access Manager: Processes login requests, handles queue, emits events."""

    def __init__(self, name: str, parent: Coupled | None, processing_delay: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay = processing_delay
        
        # Define ports
        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "account_out"))
        
        # Internal state
        self.queue = []
        self.current_request = None
        self.payload_to_send = None

    def _write_event(self, event_type: str) -> None:
        """Writes the external IO event to stdout."""
        record = {
            "time": get_current_time(),
            "model": self.name,
            "event": event_type,
            "data": {}
        }
        print(json.dumps(record), flush=True)

    def initialize(self):
        self.queue = []
        self.current_request = None
        self.payload_to_send = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # If we were processing, continue processing and reduce time remaining
        if self.phase == "PROCESSING":
            self.continuef(e)
        
        # Handle incoming requests
        for request in self.input["request_in"].values:
            # Append to queue
            self.queue.append(request)
            
            # If idle, start processing immediately
            if self.phase == "IDLE":
                self.current_request = self.queue.pop(0)
                self.hold_in("PROCESSING", self.processing_delay)

    def lambdaf(self):
        # Emit output only when in OUTPUT_READY phase
        if self.phase == "OUTPUT_READY" and self.payload_to_send is not None:
            self.output["account_out"].add(self.payload_to_send)

    def deltint(self):
        if self.phase == "PROCESSING":
            # Processing delay elapsed
            req = self.current_request
            
            # Check validity based on 'invalid' field
            # 0 = valid login, 1 = invalid login
            if req.get("invalid") == 0:
                # Valid: Prepare payload for ANV
                self.payload_to_send = {
                    "timestamp": req.get("timestamp")
                }
                # Emit external IO event
                self._write_event("account_generated")
                # Schedule output
                self.hold_in("OUTPUT_READY", 0.0)
            else:
                # Invalid: Emit logout event, no DEVS output
                self._write_event("logout")
                self.current_request = None
                self.payload_to_send = None
                
                # Check queue for next item
                if self.queue:
                    self.current_request = self.queue.pop(0)
                    self.hold_in("PROCESSING", self.processing_delay)
                else:
                    self.passivate("IDLE")
                    
        elif self.phase == "OUTPUT_READY":
            # Output sent, clear current state
            self.current_request = None
            self.payload_to_send = None
            
            # Check queue for next item
            if self.queue:
                self.current_request = self.queue.pop(0)
                self.hold_in("PROCESSING", self.processing_delay)
            else:
                self.passivate("IDLE")
        else:
            # Fallback to passive if in unexpected state
            self.passivate("IDLE")

    def exit(self):
        pass