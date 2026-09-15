import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class CheckHair(Atomic):
    """Atomic model for the Hair Inspection phase in the Barbershop simulation."""

    def __init__(self, name: str, parent: Coupled | None, inspection_time: float):
        super().__init__(name)
        self.parent = parent
        self.inspection_time = inspection_time

        self.add_in_port(Port(str, "in_cust"))
        self.add_in_port(Port(str, "done_in"))
        self.add_out_port(Port(str, "to_cut"))
        self.add_out_port(Port(str, "to_reception"))

    def initialize(self):
        """Initialize the model in the IDLE state."""
        self.passivate("IDLE")

    def _log_state(self, field: str, value: str):
        """Emit a Type A (State Change) JSONL record to stdout."""
        record = {
            "time": get_current_time(),
            "type": "state",
            "model": "checkhair",
            "field": field,
            "value": value
        }
        print(json.dumps(record), flush=True)

    def _log_message(self, port: str, content: str):
        """Emit a Type B (Communication Event) JSONL record to stdout."""
        record = {
            "time": get_current_time(),
            "type": "message",
            "model": "checkhair",
            "port": port,
            "content": content
        }
        print(json.dumps(record), flush=True)

    def deltext(self, e: float):
        """Handle external input events."""
        if self.phase == "IDLE":
            # Check for new customer from Reception
            for val in self.input["in_cust"].values:
                if val == "newcust":
                    self._log_state("customer", "newcust")
                    self.hold_in("BUSY", self.inspection_time)
                    return
        elif self.phase == "WAITING_FOR_DONE":
            # Check for done signal from CutHair
            for val in self.input["done_in"].values:
                if val == "done":
                    self._log_state("customer", "done")
                    # Schedule zero-delay output to Reception
                    self.hold_in("SENDING_TO_RECEPTION", 0.0)
                    return
        
        # Ignore 'newcust' while BUSY or WAITING_FOR_DONE, or any other inputs
        self.continuef(e)

    def lambdaf(self):
        """Generate output events at internal transitions."""
        if self.phase == "SENDING_TO_CUT":
            self._log_message("to_cut", "newcust")
            self.output["to_cut"].add("newcust")
        elif self.phase == "SENDING_TO_RECEPTION":
            self._log_message("to_reception", "done")
            self.output["to_reception"].add("done")

    def deltint(self):
        """Handle internal state transitions."""
        if self.phase == "BUSY":
            # Inspection time finished, schedule output to CutHair
            self.hold_in("SENDING_TO_CUT", 0.0)
        elif self.phase == "SENDING_TO_CUT":
            # Output sent, wait for CutHair to finish
            self.passivate("WAITING_FOR_DONE")
        elif self.phase == "SENDING_TO_RECEPTION":
            # Output sent, cycle complete, return to IDLE
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        """Cleanup method (currently no resources to release)."""
        pass