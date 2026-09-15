import json
import random
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class AAM1(Atomic):
    """Account Access Manager model for IOBS system."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "input_in"))
        self.add_out_port(Port(dict, "account_generated_out"))
        self.add_out_port(Port(dict, "logout_out"))
        self.pending = []
        self.payload_to_send = None
        self.processing_delay = 10.0

    def initialize(self):
        self.pending = []
        self.payload_to_send = None
        self.passivate("IDLE")

    def deltext(self, e):
        for packet in self.input["input_in"].values:
            self.pending.append(packet)

        if self.phase == "IDLE" and self.payload_to_send is None and self.pending:
            self._prepare_next()
            # Schedule zero-delay output for valid logins
            if self.pending[0]["valid"] == 1 and self.pending[0]["invalid"] == 0:
                self.hold_in("OUTPUT_READY", 0.0)
            else:
                # For invalid logins, emit logout and end processing immediately
                self.hold_in("LOGOUT_READY", 0.0)
        elif self.phase != "IDLE":
            self.continuef(e)

    def _prepare_next(self) -> None:
        packet = self.pending[0]
        if packet["valid"] == 1 and packet["invalid"] == 0:
            self.payload_to_send = "account_generated"
        else:
            self.payload_to_send = "logout"

    def lambdaf(self):
        if self.payload_to_send == "account_generated":
            # Emit account_generated event
            self.output["account_generated_out"].add({})
            # Emit JSONL record to stdout
            print(json.dumps({
                "time": get_current_time(),
                "model": self.name,
                "event": "account_generated",
                "data": {},
            }), flush=True)
        elif self.payload_to_send == "logout":
            # Emit logout event (no DEVS output)
            print(json.dumps({
                "time": get_current_time(),
                "model": self.name,
                "event": "logout",
                "data": {},
            }), flush=True)

    def deltint(self):
        if self.phase == "OUTPUT_READY":
            self.payload_to_send = None
            self.pending.pop(0)
            if self.pending:
                self._prepare_next()
                self.hold_in("OUTPUT_READY", 0.0)
            else:
                self.passivate("IDLE")
        elif self.phase == "LOGOUT_READY":
            self.payload_to_send = None
            self.pending.pop(0)
            if self.pending:
                self._prepare_next()
                self.hold_in("LOGOUT_READY", 0.0)
            else:
                self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass