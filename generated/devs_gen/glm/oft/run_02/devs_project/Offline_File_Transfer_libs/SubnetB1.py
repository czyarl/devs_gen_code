from xdevs.models import Atomic, Coupled, Port


class SubnetB1(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "data_out"))
        self.packet = None

    def initialize(self):
        self.packet = None
        self.passivate("passive")

    def deltext(self, e):
        if self.phase == "busy":
            self.continuef(e)
            return
        for packet in self.input["data_in"].values:
            self.packet = dict(packet)
            self.hold_in("busy", self.delay)
            return
        self.passivate("passive")

    def lambdaf(self):
        if self.phase == "busy" and self.packet is not None:
            self.output["data_out"].add(dict(self.packet))

    def deltint(self):
        self.packet = None
        self.passivate("passive")

    def exit(self):
        pass