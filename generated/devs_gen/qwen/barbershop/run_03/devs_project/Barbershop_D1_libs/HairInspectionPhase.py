import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class HairInspectionPhase(Atomic):
    """HairInspectionPhase model as specified in the locked implementation contract."""

    def __init__(self, name: str, parent: Coupled | None, inspection_duration: float):
        super().__init__(name)
        self.parent = parent
        self.inspection_duration = inspection_duration
        self.add_in_port(Port(dict, "to_cut"))
        self.add_in_port(Port(dict, "done"))
        self.add_out_port(Port(dict, "to_cut"))
        self.add_out_port(Port(dict, "to_reception"))
        self.customer = None
        self.state = "available"

    def initialize(self):
        self.customer = None
        self.state = "available"
        self.passivate("available")

    def deltext(self, e):
        if self.phase == "available":
            # Process incoming customer
            for packet in self.input["to_cut"].values:
                if self.customer is None:
                    self.customer = packet
                    # Transition to busy
                    self.state = "busy"
                    # Emit state change record
                    print(json.dumps({
                        "time": get_current_time(),
                        "type": "state",
                        "model": self.name,
                        "field": "customer",
                        "value": "newcust"
                    }), flush=True)
                    # Schedule processing completion
                    self.hold_in("PROCESSING", self.inspection_duration)
                    return
            # No customer to process, remain available
            self.passivate("available")
        elif self.phase == "PROCESSING":
            # If we get a done signal, we're done processing
            for packet in self.input["done"].values:
                # Send done back to reception
                done_msg = {
                    "time": get_current_time(),
                    "event": "done"
                }
                self.output["to_reception"].add(done_msg)
                # Emit state change record
                print(json.dumps({
                    "time": get_current_time(),
                    "type": "state",
                    "model": self.name,
                    "field": "customer",
                    "value": "done"
                }), flush=True)
                # Model becomes available again
                self.state = "available"
                self.customer = None
                self.passivate("available")
                return
            # Continue processing if no done signal
            self.continuef(e)
        else:
            self.passivate(self.phase)

    def lambdaf(self):
        now = get_current_time()
        if self.phase == "PROCESSING" and self.customer is not None:
            # Forward customer to HairCuttingPhase
            self.output["to_cut"].add(self.customer)
            # Emit message event record
            print(json.dumps({
                "time": now,
                "type": "message",
                "model": self.name,
                "port": "to_cut",
                "content": "newcust"
            }), flush=True)

    def deltint(self):
        if self.phase == "PROCESSING":
            # Model becomes available after processing
            self.state = "available"
            self.customer = None
            self.passivate("available")
        else:
            self.passivate(self.phase)

    def exit(self):
        pass