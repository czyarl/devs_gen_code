from xdevs.models import Atomic, Coupled, Port


class SubnetA2(Atomic):
    def __init__(self, name: str, parent: Coupled | None, delay: float):
        super().__init__(name)
        self.parent = parent
        self.delay = delay
        self.add_in_port(Port(int, "ack_in"))
        self.add_out_port(Port(int, "ack_out"))
        self.ack_payload = None

    def initialize(self):
        self.ack_payload = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "DELAYING":
            self.continuef(e)
            return
        for ack in self.input["ack_in"].values:
            self.ack_payload = ack
            self.hold_in("DELAYING", self.delay)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "DELAYING" and self.ack_payload is not None:
            self.output["ack_out"].add(self.ack_payload)

    def deltint(self):
        self.ack_payload = None
        self.passivate("IDLE")

    def exit(self):
        pass