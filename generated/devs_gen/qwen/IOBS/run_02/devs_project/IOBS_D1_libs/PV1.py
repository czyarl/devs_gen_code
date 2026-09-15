from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import random


class PV1(Atomic):
    """PasswordVerifier model for IOBS system.

    Receives verification from ANV1. Performs random password check (50% success per attempt).
    Eventually succeeds and forwards to BPM1. The model tracks the number of attempts made
    and emits the final result when successful. Each verification attempt takes 10 seconds
    to process, and the model advances simulation time accordingly.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "verification_in"))
        self.add_out_port(Port(dict, "verification_out"))
        self.attempts = 0
        self.in_flight = None

    def initialize(self):
        self.attempts = 0
        self.in_flight = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        for packet in self.input["verification_in"].values:
            self.attempts = 0
            self.in_flight = dict(packet)
            self.hold_in("PROCESSING", 10.0)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.in_flight is not None:
            # Emit the verification result
            result = {"success": 1, "attempts": self.attempts}
            self.output["verification_out"].add(result)

    def deltint(self):
        if self.in_flight is not None:
            # Simulate password check
            self.attempts += 1
            if random.random() < 0.5:
                # Success
                self.in_flight = None
                self.passivate("IDLE")
            else:
                # Failure, continue processing
                self.hold_in("PROCESSING", 10.0)
        else:
            self.passivate("IDLE")

    def exit(self):
        pass