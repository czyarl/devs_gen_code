from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class SubnetB2(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "ack_out"))
        self.ack = None

    def initialize(self):
        self.ack = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "DELAYING":
            self.continuef(e)
            return
        for ack in self.input["ack_in"].values:
            # Preserve the complete received object.
            self.ack = dict(ack)
            self.hold_in("DELAYING", self.delay)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "DELAYING" and self.ack is not None:
            # Forward all retained fields unchanged at the delayed event.
            self.output["ack_out"].add(dict(self.ack))

    def deltint(self):
        self.ack = None
        self.passivate("IDLE")

    def exit(self):
        pass