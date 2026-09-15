"""Atomic DEVS model for BPM (BillPaymentManager)."""

import json
import random
import sys
import time

from xdevs.models import Atomic, Coupled, Port

# Global seed setup as per requirements
random.seed(time.time_ns())

from devs_project.devs_utils.devs_context import get_current_time


class BPM(Atomic):
    """BillPaymentManager: Generates bill amounts after a processing delay."""

    def __init__(self, name: str, parent: Coupled | None, processing_delay: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay = processing_delay

        # Ports
        self.add_in_port(Port(dict, "success_in"))
        self.add_in_port(Port(dict, "balance_in"))
        self.add_out_port(Port(dict, "bill_out"))

        # Internal state
        self.remaining_balance = 0
        self.bill_amount = 0
        self.pending_success = False

    def initialize(self):
        self.remaining_balance = 0
        self.bill_amount = 0
        self.pending_success = False
        self.passivate("IDLE")

    def deltext(self, e: float):
        # Update balance if received
        for balance_data in self.input["balance_in"].values:
            self.remaining_balance = balance_data.get("remaining", 0)

        # Handle success notification
        if self.phase == "IDLE":
            for _ in self.input["success_in"].values:
                self.pending_success = True
                self.hold_in("PROCESSING", self.processing_delay)
                return
        elif self.phase == "PROCESSING":
            # Ignore inputs while processing (single in-flight)
            self.continuef(e)
        else:
            self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.pending_success:
            # Generate bill amount: random 0-40, constrained by balance
            max_amount = min(40, self.remaining_balance)
            self.bill_amount = random.randint(0, max_amount)

            # Prepare DEVS output
            current_time = get_current_time()
            payload = {
                "timestamp": current_time,
                "amount": self.bill_amount
            }
            self.output["bill_out"].add(payload)

            # Perform External IO (stdout)
            record = {
                "time": current_time,
                "model": self.name,
                "event": "bill",
                "data": {
                    "amount": self.bill_amount
                }
            }
            print(json.dumps(record), flush=True)

    def deltint(self):
        self.pending_success = False
        self.passivate("IDLE")

    def exit(self):
        pass