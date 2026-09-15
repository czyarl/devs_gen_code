from xdevs.models import Atomic, Coupled, Port
import json


class Subnet_A(Atomic):
    """Reliable, FIFO, 3s delay. Connects Sender to Server."""

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
            self.hold_in("DELAY", 3.0)

    def lambdaf(self):
        pass

    def deltint(self):
        self.passivate("IDLE")

    def exit(self):
        pass