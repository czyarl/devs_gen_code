from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class ServerReceiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None, processing_delay: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay = processing_delay
        self.add_in_port(Port(dict, "data_from_sender"))
        self.add_out_port(Port(dict, "ack_to_sender"))
        self.expected_bit = 0
        self.storage_queue = []
        self.in_flight_packet = None
        self.packet_received_time = None

    def initialize(self):
        self.expected_bit = 0
        self.storage_queue = []
        self.in_flight_packet = None
        self.packet_received_time = None
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        for packet in self.input["data_from_sender"].values:
            self.in_flight_packet = dict(packet)
            self.packet_received_time = get_current_time()
            self.hold_in("PROCESSING", self.processing_delay)
            # Emit packet_received event
            record = {
                "timestamp_ms": self.packet_received_time,
                "model": "server_receiver",
                "type": "packet_received",
                "val": {"seq": packet["seq"], "bit": packet["bit"]}
            }
            print(json.dumps(record), flush=True)
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
                self.output["ack_to_sender"].add(ack_packet)
                # Emit ack_sent_to_sender event
                record = {
                    "timestamp_ms": get_current_time(),
                    "model": "server_receiver",
                    "type": "ack_sent_to_sender",
                    "val": {"bit": bit}
                }
                print(json.dumps(record), flush=True)
                # Add to storage queue
                self.storage_queue.append(packet)
                # Flip expected bit
                self.expected_bit = 1 - self.expected_bit
            else:
                # Resend previous ACK
                prev_ack = {"bit": 1 - self.expected_bit}
                self.output["ack_to_sender"].add(prev_ack)
                # No event to emit for resend ACK

    def deltint(self):
        self.in_flight_packet = None
        self.passivate("IDLE")

    def exit(self):
        pass