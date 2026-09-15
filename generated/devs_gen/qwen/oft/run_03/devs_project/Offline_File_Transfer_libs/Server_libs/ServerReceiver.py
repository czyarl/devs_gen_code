from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class ServerReceiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "data"))
        self.add_out_port(Port(dict, "ack"))
        self.expected_bit = 0
        self.in_flight_packet = None
        self.processing_delay = 3.0
        self.storage_queue = []

    def initialize(self):
        self.expected_bit = 0
        self.in_flight_packet = None
        self.storage_queue = []
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        for packet in self.input["data"].values:
            # Emit packet_received event
            record = {
                "timestamp_ms": get_current_time() * 1000,
                "model": "server_receiver",
                "type": "packet_received",
                "val": {"seq": packet["seq"], "bit": packet["bit"]}
            }
            print(json.dumps(record), flush=True)

            self.in_flight_packet = dict(packet)
            self.hold_in("PROCESSING", self.processing_delay)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.in_flight_packet is not None:
            packet = self.in_flight_packet
            bit = packet["bit"]
            seq = packet["seq"]

            if bit == self.expected_bit:
                # Send ACK immediately
                ack_packet = {"bit": bit}
                self.output["ack"].add(ack_packet)

                # Emit ack_sent_to_sender event
                record = {
                    "timestamp_ms": get_current_time() * 1000,
                    "model": "server_receiver",
                    "type": "ack_sent_to_sender",
                    "val": {"bit": bit}
                }
                print(json.dumps(record), flush=True)

                # Store packet in queue
                self.storage_queue.append(packet)

                # Flip expected bit
                self.expected_bit = 1 - self.expected_bit
            else:
                # Resend previous ACK
                previous_ack = {"bit": 1 - self.expected_bit}
                self.output["ack"].add(previous_ack)

                # Emit ack_sent_to_sender event for resend
                record = {
                    "timestamp_ms": get_current_time() * 1000,
                    "model": "server_receiver",
                    "type": "ack_sent_to_sender",
                    "val": {"bit": 1 - self.expected_bit}
                }
                print(json.dumps(record), flush=True)

    def deltint(self):
        self.in_flight_packet = None
        self.passivate("IDLE")

    def exit(self):
        pass