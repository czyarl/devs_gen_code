import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time

class ReceptionDesk(Atomic):
    """
    Manages a bounded FIFO queue for incoming customers and enforces a fixed
    processing duration before handoff.
    """

    def __init__(self, name: str, parent: Coupled | None, queue_capacity: int, process_time: float):
        super().__init__(name)
        self.parent = parent
        self.queue_capacity = queue_capacity
        self.process_time = process_time

        # Ports
        self.add_in_port(Port(str, "cust"))
        self.add_in_port(Port(str, "to_reception"))
        self.add_out_port(Port(str, "cust"))

        # State variables
        self.queue_size = 0
        self.inspector_available = True

    def initialize(self):
        self.queue_size = 0
        self.inspector_available = True
        self.passivate("IDLE")

    def _emit_state(self):
        """Emits the state change JSONL record for total customers num."""
        record = {
            "time": get_current_time(),
            "type": "state",
            "model": "reception",
            "field": "total customers num",
            "value": str(self.queue_size)
        }
        print(json.dumps(record), flush=True)

    def _emit_message(self, content: str):
        """Emits the message JSONL record for port 'cust'."""
        record = {
            "time": get_current_time(),
            "type": "message",
            "model": "reception",
            "port": "cust",
            "content": content
        }
        print(json.dumps(record), flush=True)

    def deltext(self, e: float):
        # Handle external input 'cust' (newcust)
        for val in self.input["cust"].values:
            if val == "newcust":
                if self.queue_size < self.queue_capacity:
                    prev_size = self.queue_size
                    self.queue_size += 1
                    self._emit_state()
                    
                    # If transition from empty to non-empty, start processing
                    if prev_size == 0:
                        self.hold_in("PROCESSING", self.process_time)
                else:
                    # Queue at capacity, ignore arrival
                    pass

        # Handle external input 'to_reception' (done)
        for val in self.input["to_reception"].values:
            if val == "done":
                self.inspector_available = True
                # If currently waiting to send, trigger immediate internal transition
                if self.phase == "WAITING_TO_SEND":
                    self.hold_in("SENDING", 0.0)
                elif self.phase == "IDLE" and self.queue_size > 0:
                    # If idle but queue not empty (shouldn't happen often given logic, but safe to handle)
                    self.hold_in("PROCESSING", self.process_time)
                elif self.phase == "PROCESSING":
                    # Preserve remaining time
                    self.continuef(e)
                elif self.phase == "IDLE":
                    # Stay idle
                    self.passivate("IDLE")
                else:
                    # Preserve remaining time for other active phases
                    self.continuef(e)

        # If no specific transition was triggered by 'to_reception' logic above
        # (e.g., we were just receiving 'newcust' in IDLE or PROCESSING),
        # ensure we preserve state correctly.
        if self.phase == "PROCESSING":
            self.continuef(e)
        elif self.phase == "IDLE" and self.queue_size > 0:
             # This case handles newcust arriving when IDLE
             self.hold_in("PROCESSING", self.process_time)
        elif self.phase == "IDLE":
             self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "SENDING":
            self.output["cust"].add("newcust")
            self._emit_message("newcust")

    def deltint(self):
        if self.phase == "PROCESSING":
            # Timer expired. Check inspector availability.
            if self.inspector_available:
                self.hold_in("SENDING", 0.0)
            else:
                self.passivate("WAITING_TO_SEND")
        
        elif self.phase == "SENDING":
            # Output was just emitted. Decrement queue.
            self.queue_size -= 1
            self._emit_state()
            
            if self.queue_size > 0:
                # Process next customer
                self.hold_in("PROCESSING", self.process_time)
            else:
                # Queue empty
                self.passivate("IDLE")

    def exit(self):
        pass