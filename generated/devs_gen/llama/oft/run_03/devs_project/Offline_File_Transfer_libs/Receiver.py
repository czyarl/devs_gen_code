"""Complete implementation: Receiver Atomic DEVS model."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Receiver(Atomic):
    """Receives packets from Server via Subnet_B. Sends ACK."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "ack_out"))

    def initialize(self):
        self.passivate("WAITING")

    def deltext(self, e):
        for packet in self.input["packet_in"].values:
            self.handle_packet(packet)
        self.passivate("WAITING")

    def lambdaf(self):
        pass

    def deltint(self):
        pass

    def exit(self):
        pass

    def handle_packet(self, packet: dict):
        # Send ACK to Server
        ack = {"bit": packet["bit"]}
        self.output["ack_out"].add(ack)

        # Print received packet and sent ACK as JSONL records
        current_time = get_current_time()
        print(json.dumps({
            "timestamp_ms": current_time * 1000,
            "model": "receiver",
            "type": "packet_received",
            "val": packet
        }), flush=True)
        print(json.dumps({
            "timestamp_ms": current_time * 1000,
            "model": "receiver",
            "type": "ack_sent",
            "val": ack
        }), flush=True)