"""Complete implementation of ANV1."""

import json
import random
from devs_project.devs_utils.devs_context import get_current_time

from xdevs.models import Atomic, Coupled, Port

class ANV1(Atomic):
    """Account Number Verifier."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "input"))
        self.add_out_port(Port(dict, "PV1_in"))
        self.external_io = [{"target": "stdout", "content": {"time": 0.0, "model": "ANV1", "event": "verification", "data": {"pass": 1, "fail": 0}}}] 

    def initialize(self):
        self.passivate("WAITING")

    def deltext(self, e):
        for packet in self.input["input"].values:
            self.account = packet
            self.hold_in("VERIFICATION", 10.0)

    def lambdaf(self):
        if random.random() < 0.5:
            self.output["PV1_in"].add({"pass": 1, "fail": 0})
            print(json.dumps({"time": get_current_time(), "model": "ANV1", "event": "verification", "data": {"pass": 1, "fail": 0}}), flush=True)
        else:
            self.output["PV1_in"].add({"pass": 0, "fail": 1})
            print(json.dumps({"time": get_current_time(), "model": "ANV1", "event": "verification", "data": {"pass": 0, "fail": 1}}), flush=True)

    def deltint(self):
        self.passivate("WAITING")

    def exit(self):
        pass