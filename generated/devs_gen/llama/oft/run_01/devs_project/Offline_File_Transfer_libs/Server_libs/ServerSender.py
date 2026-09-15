from xdevs.models import Atomic, Coupled, Port
import json

class ServerSender(Atomic):
    def __init__(
        self,
        name: str,
        parent: Coupled | None,
    ):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "storage_queue_in"))
        self.add_in_port(Port(bool, "download_valve"))
        self.add_in_port(Port(dict, "ack_from_receiver"))
        self.add_out_port(Port(dict, "downloadable_packets_out"))
        self.add_out_port(Port(dict, "ack_out"))

        self.storage_queue = []
        self.download_allowed = False
        self.waiting_for_ack = False
        self.current_packet = None

    def initialize(self):
        self.storage_queue = []
        self.download_allowed = False
        self.waiting_for_ack = False
        self.current_packet = None
        self.passivate("idle")

    def deltext(self, e):
        for packet in self.input["storage_queue_in"].values:
            self.storage_queue.append(packet)
        
        for valve in self.input["download_valve"].values:
            self.download_allowed = valve

        for ack in self.input["ack_from_receiver"].values:
            if self.waiting_for_ack:
                self.waiting_for_ack = False
                if self.storage_queue:
                    self.current_packet = self.storage_queue.pop(0)
                else:
                    self.passivate("idle")

        if self.download_allowed and not self.waiting_for_ack and self.storage_queue:
            self.current_packet = self.storage_queue.pop(0)
            self.waiting_for_ack = True
            self.output["downloadable_packets_out"].add(self.current_packet)

        self.hold_in(self.phase, 0.0)

    def lambdaf(self):
        if self.phase == "idle":
            pass
        else:
            self.passivate("idle")

    def deltint(self):
        pass

    def exit(self):
        pass