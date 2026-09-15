import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time

class HairInspector(Atomic):
    """Implements the 'checkhair' logic as a serial processor with a two-phase lifecycle per customer."""

    def __init__(self, name: str, parent: Coupled | None, process_time: float):
        super().__init__(name)
        self.parent = parent
        self.process_time = process_time
        
        # Input Ports
        self.add_in_port(Port(str, "cust"))
        self.add_in_port(Port(str, "out"))
        
        # Output Ports
        self.add_out_port(Port(str, "to_cut"))
        self.add_out_port(Port(str, "to_reception"))

    def initialize(self):
        """Initially 'available'."""
        self.passivate("available")

    def deltext(self, e: float):
        """Handle external transitions."""
        current_time = get_current_time()
        
        # State 1: Available
        # Upon receiving 'newcust' on port 'cust', it records a state change to 'newcust' (JSONL),
        # sets an internal timer for 'process_time' (7s), and becomes 'busy'.
        if self.phase == "available":
            if not self.input["cust"].empty():
                # Assuming we process the first valid input found
                for val in self.input["cust"].values:
                    if val == "newcust":
                        # Record state change
                        record = {
                            "time": current_time,
                            "type": "state",
                            "model": "checkhair",
                            "field": "customer",
                            "value": "newcust"
                        }
                        print(json.dumps(record), flush=True)
                        
                        # Become busy for process_time
                        self.hold_in("busy", self.process_time)
                        return
        
        # State 2: Waiting (for done from HairCutter)
        # While waiting, it ignores further 'cust' inputs.
        elif self.phase == "waiting":
            if not self.input["out"].empty():
                for val in self.input["out"].values:
                    if val == "done":
                        # Upon receiving 'done', it sends 'done' via port 'to_reception' (JSONL),
                        # records a state change to 'done' (JSONL), and returns to 'available'.
                        
                        # Record state change
                        record = {
                            "time": current_time,
                            "type": "state",
                            "model": "checkhair",
                            "field": "customer",
                            "value": "done"
                        }
                        print(json.dumps(record), flush=True)
                        
                        # Schedule output of 'done' to reception immediately
                        self.hold_in("send_reception", 0.0)
                        return

        # If no transition triggered, preserve remaining time
        self.continuef(e)

    def lambdaf(self):
        """Handle output function."""
        current_time = get_current_time()
        
        # When the timer expires (internal transition), it sends 'newcust' via port 'to_cut' (JSONL)
        # and enters a waiting state.
        if self.phase == "busy":
            self.output["to_cut"].add("newcust")
            
            # Record message emission
            record = {
                "time": current_time,
                "type": "message",
                "model": "checkhair",
                "port": "to_cut",
                "content": "newcust"
            }
            print(json.dumps(record), flush=True)
            
        # Upon receiving 'done' on port 'out' (external transition), it sends 'done' via port 'to_reception' (JSONL)
        elif self.phase == "send_reception":
            self.output["to_reception"].add("done")
            
            # Record message emission
            record = {
                "time": current_time,
                "type": "message",
                "model": "checkhair",
                "port": "to_reception",
                "content": "done"
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        """Handle internal transitions."""
        # Transition from 'busy' to 'waiting'
        if self.phase == "busy":
            self.passivate("waiting")
        
        # Transition from 'send_reception' to 'available'
        elif self.phase == "send_reception":
            self.passivate("available")
        
        else:
            # Should not happen if logic is correct, but passivate to be safe
            self.passivate("available")

    def exit(self):
        """Cleanup."""
        pass