"""ANV1: Account Number Verifier model."""

import random
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ANV1(Atomic):
    """Verifies account numbers received from AAM1. Performs a 50% random check:
    if pass, forwards the verification result to PV1; if fail, ends processing
    for this request. The verification result is a dictionary with 'pass' and
    'fail' keys set to 1 or 0. The model does not emit any DEVS output when
    failing. The model uses simulation time for all internal timing and state
    management. It starts at time zero and processes inputs as they arrive
    through the 'account_generated' input port. The model does not maintain any
    persistent state beyond the immediate processing of one input.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "account_generated"))
        self.add_out_port(Port(dict, "verification"))
        self.in_flight = None

    def initialize(self):
        self.in_flight = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        for item in self.input["account_generated"].values:
            self.in_flight = dict(item)
            # Perform 50% random check
            if random.random() < 0.5:
                # Pass: schedule output
                self.hold_in("OUTPUT_READY", 0.0)
            else:
                # Fail: end processing, do not emit output
                self.passivate("IDLE")
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self.in_flight is not None:
            # Emit verification result: pass=1, fail=0
            result = {"pass": 1, "fail": 0}
            self.output["verification"].add(result)
            self.in_flight = None

    def deltint(self):
        if self.phase == "OUTPUT_READY":
            # After emitting output, go back to idle
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass