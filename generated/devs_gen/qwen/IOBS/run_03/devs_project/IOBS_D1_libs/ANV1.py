"""Atomic DEVS model ANV1 performing random account verification with 50% pass rate."""

import json
import random
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ANV1(Atomic):
    """Account Number Verifier model."""

    def __init__(self, name: str, parent: Coupled | None, processing_delay: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay = processing_delay
        self.add_in_port(Port(dict, "account_in"))
        self.add_out_port(Port(dict, "account_out"))
        self.in_flight = None

    def initialize(self):
        self.in_flight = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        for account in self.input["account_in"].values:
            self.in_flight = dict(account)
            self.hold_in("PROCESSING", self.processing_delay)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.in_flight is not None:
            # Perform random verification
            outcome = random.choice([True, False])  # 50% chance pass/fail
            
            # Emit verification event to stdout
            event_data = {
                "time": get_current_time(),
                "model": "ANV1",
                "event": "verification",
                "data": {
                    "pass": 1 if outcome else 0,
                    "fail": 1 if not outcome else 0
                }
            }
            print(json.dumps(event_data), flush=True)
            
            # Forward to PV if pass
            if outcome:
                self.output["account_out"].add(dict(self.in_flight))

    def deltint(self):
        self.in_flight = None
        self.passivate("IDLE")

    def exit(self):
        pass