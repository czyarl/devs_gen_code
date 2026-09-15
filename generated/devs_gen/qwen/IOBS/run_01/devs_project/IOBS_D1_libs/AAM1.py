"""Atomic DEVS model AAM1 implementing the AccountAccessManager logic."""

import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class AAM1(Atomic):
    """AccountAccessManager model for handling login requests."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "input"))
        self.add_out_port(Port(dict, "account_generated"))
        self.add_out_port(Port(dict, "logout"))
        self.pending = None

    def initialize(self):
        self.pending = None
        self.passivate("IDLE")

    def deltext(self, e):
        # Process all incoming input events
        for packet in self.input["input"].values:
            if self.pending is not None:
                # Should not happen according to contract, but handle gracefully
                raise RuntimeError("AAM1 received multiple inputs without processing")
            self.pending = packet

        if self.phase == "IDLE" and self.pending is not None:
            # Schedule zero-delay output processing
            self.hold_in("PROCESSING", 0.0)
        elif self.phase != "IDLE":
            self.continuef(e)

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.pending is not None:
            packet = self.pending
            valid = packet["valid"]
            invalid = packet["invalid"]

            # According to contract: valid=1 and invalid=0 -> forward to ANV
            # valid=1 and invalid=1 -> emit logout, do not forward
            if valid == 1 and invalid == 0:
                # Forward to ANV
                self.output["account_generated"].add({})
            elif valid == 1 and invalid == 1:
                # Emit logout event (stdout-only, not a DEVS output port)
                print(json.dumps({
                    "time": get_current_time(),
                    "model": "AAM1",
                    "event": "logout",
                    "data": {},
                }), flush=True)

            # Clear pending packet after handling
            self.pending = None

    def deltint(self):
        if self.phase == "PROCESSING":
            # After processing, passivate
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")
    def exit(self):
        pass
