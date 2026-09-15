import json
import random
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time

class PV(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "request_in"))
        self.add_out_port(Port(dict, "success_request_out"))

    def initialize(self):
        self.passivate("IDLE")

    def deltext(self, e):
        for request in self.input["request_in"].values:
            self.request = request
            self.attempts = 1
            self.hold_in("PROCESSING", 10.0)

    def lambdaf(self):
        if self.phase != "PROCESSING":
            return

        if random.random() < 0.5:
            self.output["success_request_out"].add({
                "time": get_current_time(),
                "success": 1,
                "attempts": self.attempts
            })
            print(json.dumps({
                "time": get_current_time(),
                "model": "PV",
                "event": "verification",
                "data": {"success": 1, "attempts": self.attempts}
            }), flush=True)
        else:
            self.attempts += 1
            self.hold_in("PROCESSING", 0.0)

    def deltint(self):
        pass

    def exit(self):
        pass