"""Atomic DEVS model for the Receiver component in the file transfer simulation."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Receiver(Atomic):
    """Receives data packets from Server via SubnetB1, processes them with a 10-second delay,
    and sends ACKs back to Server via SubnetB2. Maintains expected bit state and handles
    packet sequencing according to the Alternating Bit Protocol.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "data"))
        self.add_out_port(Port(dict, "ack"))
        self.expected_bit = 0
        self.current_packet = None
        self.payload_to_send = None

    def _write_event(self, event_type: str, payload: dict) -> None:
        print(json.dumps({
            "timestamp_ms": get_current_time(),
            "model": "receiver",
            "type": event_type,
            "val": payload,
        }), flush=True)

    def _start_processing(self, packet: dict) -> None:
        self.current_packet = dict(packet)
        self._write_event("processing_started", {
            "seq": self.current_packet["seq"],
            "duration": 10000.0,
        })
        self.hold_in("PROCESSING", 10000.0)  # 10 seconds processing delay

    def initialize(self):
        self.expected_bit = 0
        self.current_packet = None
        self.payload_to_send = None
        self.passivate("IDLE")

    def deltext(self, e):
        was_processing = self.phase == "PROCESSING"
        if was_processing:
            self.continuef(e)

        for packet in self.input["data"].values:
            if self.current_packet is None:
                self._start_processing(packet)
            # If already processing, ignore new packets (no queueing in this model)

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self.payload_to_send is not None:
            self.output["ack"].add(dict(self.payload_to_send))

    def deltint(self):
        if self.phase == "PROCESSING":
            # Processing complete, emit ack
            ack_bit = self.current_packet["bit"]
            self.payload_to_send = {"bit": ack_bit}
            self._write_event("ack_sent", {"bit": ack_bit})
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase == "OUTPUT_READY":
            # Ack sent, update expected bit if needed
            if self.current_packet["bit"] == self.expected_bit:
                self.expected_bit = 1 - self.expected_bit  # Flip the bit
            self.current_packet = None
            self.payload_to_send = None
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass