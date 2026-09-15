from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class SubnetA1(Atomic):
    """Provides reliable FIFO communication with 3s delay from Sender to Server."""

    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "data_out"))
        self.in_flight = None

    def initialize(self):
        self.in_flight = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        for packet in self.input["data_in"].values:
            self.in_flight = dict(packet)
            self.hold_in("PROCESSING", self.delay)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.in_flight is not None:
            self.output["data_out"].add(dict(self.in_flight))

    def deltint(self):
        self.in_flight = None
        self.passivate("IDLE")

    def exit(self):
        pass