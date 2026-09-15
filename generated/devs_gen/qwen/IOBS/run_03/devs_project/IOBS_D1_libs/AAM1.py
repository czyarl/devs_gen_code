from xdevs.models import Atomic, Coupled, Port
import json
import sys
from devs_project.devs_utils.devs_context import get_current_time


class AAM1(Atomic):
    def __init__(self, name: str, parent: Coupled | None, processing_delay: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay = processing_delay
        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "account_out"))
        self.current_request = None

    def initialize(self):
        self.current_request = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        for request in self.input["request_in"].values:
            if request["valid"] == 1 and request["invalid"] == 1:
                # Invalid login: emit logout event and do not forward
                event = {
                    "time": get_current_time(),
                    "model": "AAM1",
                    "event": "logout",
                    "data": {}
                }
                print(json.dumps(event), flush=True)
            elif request["valid"] == 1 and request["invalid"] == 0:
                # Valid login: store request and schedule processing
                self.current_request = dict(request)
                self.hold_in("PROCESSING", self.processing_delay)
                return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.current_request is not None:
            # Forward valid request to ANV
            self.output["account_out"].add(dict(self.current_request))
            # Emit account_generated event
            event = {
                "time": get_current_time(),
                "model": "AAM1",
                "event": "account_generated",
                "data": {}
            }
            print(json.dumps(event), flush=True)

    def deltint(self):
        self.current_request = None
        self.passivate("IDLE")

    def exit(self):
        pass