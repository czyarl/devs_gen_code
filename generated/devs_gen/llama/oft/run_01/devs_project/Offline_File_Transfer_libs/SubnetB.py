"""Complete implementation of SubnetB."""

from xdevs.models import Atomic, Coupled, Port
import json
import sys


class SubnetB(Atomic):
    """Reliable, FIFO, fixed 3s delay to data packets."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "data_out"))

    def initialize(self):
        self.passivate("IDLE")

    def deltext(self, e):
        for packet in self.input["data_in"].values:
            self.output["data_out"].add(dict(packet))
            self.hold_in("SENDING", 3.0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.passivate("IDLE")

    def exit(self):
        pass