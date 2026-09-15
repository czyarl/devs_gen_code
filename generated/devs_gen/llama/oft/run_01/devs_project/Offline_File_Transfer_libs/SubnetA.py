"""Complete pattern: reliable, FIFO, fixed 3s delay subnet."""

from xdevs.models import Atomic, Coupled, Port
import json
import sys


class SubnetA(Atomic):
    """Reliable, FIFO, fixed 3s delay subnet."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "data_out"))
        self.waiting = []

    def initialize(self):
        self.waiting = []
        self.passivate("IDLE")

    def deltext(self, e):
        for item in self.input["data_in"].values:
            self.waiting.append(dict(item))

        if self.phase == "IDLE" and self.waiting:
            self.hold_in("PROCESSING", 3.0)

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.waiting:
            self.output["data_out"].add(self.waiting.pop(0))

    def deltint(self):
        if self.waiting:
            self.hold_in("PROCESSING", 3.0)
        else:
            self.passivate("IDLE")

    def exit(self):
        pass