"""PV1: Password Verifier model implementing random verification with 50% success chance."""

import json
import random
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class PV1(Atomic):
    """Password Verifier model with random 50% success chance per attempt."""

    def __init__(self, name: str, parent: Coupled | None, processing_delay: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay = processing_delay
        self.add_in_port(Port(dict, "account_in"))
        self.add_out_port(Port(dict, "account_out"))
        self.current_account = None
        self.attempts = 0

    def initialize(self):
        self.current_account = None
        self.attempts = 0
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        for account in self.input["account_in"].values:
            self.current_account = dict(account)
            self.attempts = 0
            self.hold_in("PROCESSING", self.processing_delay)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.current_account is not None:
            # Emit verification event to stdout
            event_data = {
                "time": get_current_time(),
                "model": "PV1",
                "event": "verification",
                "data": {
                    "success": 1,
                    "attempts": self.attempts
                }
            }
            print(json.dumps(event_data), flush=True)

    def deltint(self):
        if self.current_account is not None:
            # Increment attempt count
            self.attempts += 1

            # Perform random verification (50% chance of success)
            if random.random() < 0.5:
                # Verification successful, forward to BPM
                self.output["account_out"].add(dict(self.current_account))
                self.current_account = None
                self.attempts = 0
                self.passivate("IDLE")
            else:
                # Verification failed, continue trying
                self.hold_in("PROCESSING", self.processing_delay)
        else:
            self.passivate("IDLE")

    def exit(self):
        pass