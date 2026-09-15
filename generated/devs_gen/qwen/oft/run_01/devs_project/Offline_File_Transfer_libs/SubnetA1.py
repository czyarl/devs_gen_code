"""Atomic DEVS model for SubnetA1 with fixed 3s delay."""

from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class SubnetA1(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "data_out"))
        self.packet = None

    def initialize(self):
        self.packet = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "DELAYING":
            self.continuef(e)
            return
        for packet in self.input["data_in"].values:
            # Preserve the complete received object.
            self.packet = dict(packet)
            self.hold_in("DELAYING", self.delay)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "DELAYING" and self.packet is not None:
            # Forward all retained fields unchanged at the delayed event.
            self.output["data_out"].add(dict(self.packet))

    def deltint(self):
        self.packet = None
        self.passivate("IDLE")

    def exit(self):
        pass