from xdevs.models import Atomic, Coupled, Port
import json
import sys


class Subnet_B(Atomic):
    """Reliable, FIFO, 3s delay. Connects Server to Receiver."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "packet_out"))

    def initialize(self):
        self.passivate("IDLE")

    def deltext(self, e):
        for packet in self.input["packet_in"].values:
            self.output["packet_out"].add(dict(packet))

    def lambdaf(self):
        pass

    def deltint(self):
        self.hold_in("IDLE", 3.0)

    def exit(self):
        pass