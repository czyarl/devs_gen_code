import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class CheckHair(Atomic):
    """Atomic model implementing the Hair Inspection Phase."""

    def __init__(self, name: str, parent: Coupled | None, process_time: float):
        super().__init__(name)
        self.parent = parent
        self.process_time = process_time
        
        # Input Ports
        self.add_in_port(Port(str, "cust_in"))
        self.add_in_port(Port(str, "cut_done"))
        
        # Output Ports
        self.add_out_port(Port(str, "to_cut"))
        self.add_out_port(Port(str, "to_reception"))
        
        # Internal State
        self.current_customer = None

    def initialize(self):
        """Initialize the model to the 'available' state."""
        self.current_customer = None
        self.passivate("available")

    def deltext(self, e: float):
        """Handle external inputs."""
        if self.phase == "available":
            # Check for 'newcust' on cust_in
            for val in self.input["cust_in"].values:
                if val == "newcust":
                    self.current_customer = "newcust"
                    # Log state change: customer -> newcust
                    self._log_state("customer", "newcust")
                    # Schedule internal transition after process_time
                    self.hold_in("busy_inspecting", self.process_time)
                    return
            # If no input, continue waiting (passive)
            self.continuef(e)

        elif self.phase == "waiting_for_cut":
            # Check for 'done' on cut_done
            for val in self.input["cut_done"].values:
                if val == "done":
                    # Log state change: customer -> done
                    self._log_state("customer", "done")
                    # Schedule immediate internal transition (zero-delay)
                    self.hold_in("reply_ready", 0.0)
                    return
            # If no input, continue waiting
            self.continuef(e)
        
        else:
            # Ignore inputs in other states (e.g., busy_inspecting)
            self.continuef(e)

    def lambdaf(self):
        """Handle output events."""
        if self.phase == "busy_inspecting":
            # Output 'newcust' to CutHair
            self.output["to_cut"].add("newcust")
            # Log message emission
            self._log_message("to_cut", "newcust")
            
        elif self.phase == "reply_ready":
            # Output 'done' to Reception
            self.output["to_reception"].add("done")
            # Log message emission
            self._log_message("to_reception", "done")

    def deltint(self):
        """Handle internal transitions."""
        if self.phase == "busy_inspecting":
            # Transition to waiting for cut to finish
            self.passivate("waiting_for_cut")
            
        elif self.phase == "reply_ready":
            # Return to available state
            self.current_customer = None
            self.passivate("available")
            
        else:
            # Should not happen if logic is correct, but passivate as fallback
            self.passivate("available")

    def exit(self):
        """Cleanup on simulation exit."""
        pass

    def _log_state(self, field: str, value):
        """Helper to log state changes to stdout as JSONL."""
        record = {
            "time": get_current_time(),
            "type": "state",
            "model": self.name,
            "field": field,
            "value": value
        }
        print(json.dumps(record), flush=True)

    def _log_message(self, port: str, content: str):
        """Helper to log message emissions to stdout as JSONL."""
        record = {
            "time": get_current_time(),
            "type": "message",
            "model": self.name,
            "port": port,
            "content": content
        }
        print(json.dumps(record), flush=True)