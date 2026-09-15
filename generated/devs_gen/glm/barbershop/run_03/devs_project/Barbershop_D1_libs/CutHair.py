"""Atomic DEVS model for the Hair Cutting Phase (CutHair)."""

import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class CutHair(Atomic):
    """Simulates the hair cutting phase of the barbershop.

    The model maintains a cumulative counter of customers who have finished
    cutting (`total customer done`) and operates in two phases: `idle` and `busy`.

    Upon initialization, the model starts in the `idle` phase with an infinite
    time advance. When an external input 'newcust' is received on port `cust_in`
    while in the `idle` phase, the model transitions to the `busy` phase and
    sets its time advance to the `process_time` (20.0 seconds).

    Any inputs received while in the `busy` phase are ignored to enforce the
    single-customer constraint.

    When the internal transition fires (after 20.0 seconds), the model increments
    the `total customer done` counter, writes a state change record to stdout,
    outputs the literal string 'done' on port `out`, writes a message event
    record to stdout, and transitions back to the `idle` phase with an infinite
    time advance.
    """

    def __init__(self, name: str, parent: Coupled | None, process_time: float):
        super().__init__(name)
        self.parent = parent
        self.process_time = process_time

        # Input port: receives 'newcust' from CheckHair
        self.add_in_port(Port(str, "cust_in"))

        # Output port: sends 'done' to CheckHair
        self.add_out_port(Port(str, "out"))

        # Internal state
        self.total_customer_done = 0

    def initialize(self):
        """Initialize the model to the idle state."""
        self.total_customer_done = 0
        self.passivate("idle")

    def deltext(self, e: float):
        """Handle external input events."""
        if self.phase == "busy":
            # Ignore inputs while busy to enforce single-customer constraint
            self.continuef(e)
            return

        # Check for input only if idle
        if self.phase == "idle":
            # Iterate over inputs (though we expect only one 'newcust' per transition)
            for _ in self.input["cust_in"].values:
                # Transition to busy phase for the duration of the process_time
                self.hold_in("busy", self.process_time)
                # Once we accept a customer, we ignore any others in this bag
                return

        # If no input received, stay idle
        self.passivate("idle")

    def lambdaf(self):
        """Generate output when the internal transition fires."""
        if self.phase == "busy":
            # Output the literal string 'done' on port 'out'
            self.output["out"].add("done")

    def deltint(self):
        """Handle internal state transitions."""
        if self.phase == "busy":
            # Increment the counter
            self.total_customer_done += 1

            # Get current simulation time for logging
            current_time = get_current_time()

            # 1. Write state change record to stdout
            state_record = {
                "time": current_time,
                "type": "state",
                "model": "cuthair",
                "field": "total customer done",
                "value": self.total_customer_done
            }
            print(json.dumps(state_record), flush=True)

            # 2. Write message event record to stdout
            # Note: This corresponds to the 'done' message being sent via port 'out'
            message_record = {
                "time": current_time,
                "type": "message",
                "model": "cuthair",
                "port": "out",
                "content": "done"
            }
            print(json.dumps(message_record), flush=True)

            # Transition back to idle
            self.passivate("idle")

    def exit(self):
        """Cleanup method (currently no specific cleanup required)."""
        pass