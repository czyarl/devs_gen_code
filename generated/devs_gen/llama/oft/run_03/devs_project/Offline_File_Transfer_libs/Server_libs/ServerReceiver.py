"""Complete pattern: sequential processing, one waiting slot, and timed JSONL IO."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ServerReceiver(Atomic):
    """Receives packets from Sender via Subnet_A. Forwards to storage and sends ACK."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "ack_out"))
        self.add_out_port(Port(list, "storage_queue"))
        self.expected_bit = 0
        self.packet_to_ack = None

    def _write_event(self, event: str, payload: dict) -> None:
        print(json.dumps({
            "time": get_current_time(),
            "event": event,
            "payload": payload,
        }), flush=True)

    def initialize(self):
        self.expected_bit = 0
        self.packet_to_ack = None
        self.passivate("IDLE")

    def deltext(self, e):
        was_idle = self.phase == "IDLE"
        if was_idle:
            self.continuef(e)

        for packet in self.input["packet_in"].values:
            self._write_event("packet_received", packet)
            self.packet_to_ack = packet
            self.hold_in("PROCESSING", 3.0)

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self.packet_to_ack is not None:
            self.output["ack_out"].add({"bit": self.packet_to_ack["bit"]})
            self.output["storage_queue"].add(self.packet_to_ack)
            self.packet_to_ack = None
            self.expected_bit = 1 - self.expected_bit

    def deltint(self):
        if self.phase == "PROCESSING":
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase == "OUTPUT_READY":
            self.packet_to_ack = None
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass