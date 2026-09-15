from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time
import json
import sys


class ServerReceiver(Atomic):
    def __init__(self, name: str, parent: Coupled | None, processing_delay: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay = processing_delay
        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "ack_out"))
        self.expected_bit = 0
        self.storage_queue = []
        self.in_flight_packet = None
        self.in_flight_time = 0.0

    def initialize(self):
        self.expected_bit = 0
        self.storage_queue = []
        self.in_flight_packet = None
        self.in_flight_time = 0.0
        self.passivate("IDLE")

    def deltext(self, e):
        if self.phase == "PROCESSING":
            self.continuef(e)
            return

        for packet in self.input["data_in"].values:
            # Record packet arrival
            timestamp = get_current_time()
            record = {
                "timestamp_ms": timestamp,
                "model": "server_receiver",
                "type": "packet_received",
                "val": packet
            }
            print(json.dumps(record), flush=True)

            self.in_flight_packet = dict(packet)
            self.in_flight_time = get_current_time()
            self.hold_in("PROCESSING", self.processing_delay)
            return
        self.passivate("IDLE")

    def lambdaf(self):
        if self.phase == "PROCESSING" and self.in_flight_packet is not None:
            packet = self.in_flight_packet
            bit = packet["bit"]
            seq = packet["seq"]

            # Check if bit matches expected bit
            if bit == self.expected_bit:
                # Send ACK immediately
                ack = {"bit": bit}
                self.output["ack_out"].add(ack)
                timestamp = get_current_time()
                record = {
                    "timestamp_ms": timestamp,
                    "model": "server_receiver",
                    "type": "ack_sent_to_sender",
                    "val": ack
                }
                print(json.dumps(record), flush=True)

                # Push to storage queue
                self.storage_queue.append(packet)

                # Flip expected bit
                self.expected_bit = 1 - self.expected_bit
            else:
                # Duplicate packet - resend previous ACK
                prev_bit = 1 - self.expected_bit
                ack = {"bit": prev_bit}
                self.output["ack_out"].add(ack)
                timestamp = get_current_time()
                record = {
                    "timestamp_ms": timestamp,
                    "model": "server_receiver",
                    "type": "ack_sent_to_sender",
                    "val": ack
                }
                print(json.dumps(record), flush=True)

    def deltint(self):
        self.in_flight_packet = None
        self.in_flight_time = 0.0
        self.passivate("IDLE")

    def exit(self):
        pass