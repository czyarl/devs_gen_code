import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class HairCutting(Atomic):
    """Processes customers with fixed 20-second duration and signals completion back to HairInspection."""

    def __init__(self, name: str, parent: Coupled | None, cutting_time: float):
        super().__init__(name)
        self.parent = parent
        self.cutting_time = cutting_time
        self.add_in_port(Port(str, "to_cut"))
        self.add_out_port(Port(str, "out"))
        self.customer_count = 0
        self.current_customer = None
        self.is_processing = False

    def initialize(self):
        self.customer_count = 0
        self.current_customer = None
        self.is_processing = False
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        # Handle incoming customer
        for customer in self.input["to_cut"].values:
            if self.current_customer is None:
                self.current_customer = customer
                self.is_processing = True
                self.hold_in("PROCESSING", self.cutting_time)
                # Log state change: customer started processing
                now = get_current_time()
                print(json.dumps({
                    "time": now,
                    "type": "state",
                    "model": self.name,
                    "field": "total customer done",
                    "value": self.customer_count
                }), flush=True)
                # Log message sent
                print(json.dumps({
                    "time": now,
                    "type": "message",
                    "model": self.name,
                    "port": "to_cut",
                    "content": customer
                }), flush=True)
                return
        self.passivate("IDLE")

    def lambdaf(self):
        now = get_current_time()
        if self.phase == "PROCESSING" and self.current_customer is not None:
            # Log completion message
            print(json.dumps({
                "time": now,
                "type": "message",
                "model": self.name,
                "port": "out",
                "content": "done"
            }), flush=True)
            # Log state change: customer done
            self.customer_count += 1
            print(json.dumps({
                "time": now,
                "type": "state",
                "model": self.name,
                "field": "total customer done",
                "value": self.customer_count
            }), flush=True)

    def deltint(self):
        if self.phase == "PROCESSING":
            self.current_customer = None
            self.is_processing = False
        self.passivate("IDLE")

    def exit(self):
        pass