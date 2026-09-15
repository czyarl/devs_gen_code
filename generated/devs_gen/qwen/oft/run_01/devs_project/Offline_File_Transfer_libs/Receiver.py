from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class Receiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None, processing_delay: float, link_delay: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay = processing_delay
        self.link_delay = link_delay
        self.add_in_port(Port(dict, "data_from_server"))
        self.add_out_port(Port(dict, "ack_to_server"))
        self.current_packet = None

    def initialize(self):
        self.current_packet = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        for packet in self.input["data_from_server"].values:
            self.current_packet = dict(packet)
            # Emit processing_started event to stdout
            record = {
                "timestamp_ms": get_current_time(),
                "model": "receiver",
                "type": "processing_started",
                "val": {
                    "seq": self.current_packet["seq"],
                    "duration": int(self.processing_delay)
                }
            }
            print(json.dumps(record), flush=True)
            self.hold_in("PROCESSING", self.processing_delay)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.current_packet is not None:
            # Prepare ACK packet
            ack_packet = {"bit": self.current_packet["bit"]}
            self.output["ack_to_server"].add(ack_packet)

    def deltint(self):
        if self.phase == "PROCESSING" and self.current_packet is not None:
            # Emit ack_sent event to stdout
            record = {
                "timestamp_ms": get_current_time(),
                "model": "receiver",
                "type": "ack_sent",
                "val": {
                    "bit": self.current_packet["bit"]
                }
            }
            print(json.dumps(record), flush=True)
            self.current_packet = None
            self.passivate("IDLE")

    def exit(self):
        pass