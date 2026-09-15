from xdevs.models import Atomic, Coupled, Port
import json
from devs_project.devs_utils.devs_context import get_current_time

class ServerReceiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "uploaded_packets_in"))
        self.add_out_port(Port(dict, "ack_out"))
        self.add_out_port(Port(dict, "storage_queue_out"))
        self.expected_bit = 0
        self.packet_in_flight = None

    def initialize(self):
        self.expected_bit = 0
        self.packet_in_flight = None
        self.passivate("IDLE")

    def deltext(self, e):
        for packet in self.input["uploaded_packets_in"].values:
            self.packet_in_flight = packet
            self.hold_in("PROCESSING", 3.0)

    def lambdaf(self):
        if self.phase == "PROCESSING":
            if self.packet_in_flight['bit'] == self.expected_bit:
                self.output["ack_out"].add({'bit': self.expected_bit})
                self.output["storage_queue_out"].add(self.packet_in_flight)
                self.expected_bit = 1 - self.expected_bit
            else:
                self.output["ack_out"].add({'bit': self.expected_bit})
        self.packet_in_flight = None
        self.passivate("IDLE")

    def deltint(self):
        pass

    def exit(self):
        pass