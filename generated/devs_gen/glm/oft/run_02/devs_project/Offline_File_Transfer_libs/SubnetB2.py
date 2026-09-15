from xdevs.models import Atomic, Coupled, Port


class SubnetB2(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        self.add_in_port(Port(int, "ack_in"))
        self.add_out_port(Port(int, "ack_out"))
        self.payload = None

    def initialize(self):
        self.payload = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        if self.phase == "DELAYING":
            self.continuef(e)
            return

        for payload in self.input["ack_in"].values:
            self.payload = payload
            self.hold_in("DELAYING", self.delay)
            return

        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "DELAYING" and self.payload is not None:
            self.output["ack_out"].add(self.payload)

    def deltint(self):
        self.payload = None
        self.passivate("IDLE")

    def exit(self):
        pass