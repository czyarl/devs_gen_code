"""ServerSender: Atomic DEVS model for managing packet forwarding to Receiver."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ServerSender(Atomic):
    """Manages packet forwarding to Receiver based on download permission, queue status, and ACK waiting state."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        self.add_in_port(Port(dict, "download_valve"))
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "data_out"))
        self.download_allowed = False
        self.waiting_for_ack = False
        self.packet_queue = []
        self.next_bit = 0

    def _write_event(self, event_type: str, payload: dict) -> None:
        print(json.dumps({
            "timestamp_ms": get_current_time(),
            "model": "server_sender",
            "type": event_type,
            "val": payload,
        }), flush=True)

    def initialize(self):
        self.download_allowed = False
        self.waiting_for_ack = False
        self.packet_queue = []
        self.next_bit = 0
        self.passivate("IDLE")

    def deltext(self, e):
        # Process download valve changes
        for valve_change in self.input["download_valve"].values:
            self.download_allowed = valve_change["allowed"]
            self._write_event("download_valve_change", {"allowed": self.download_allowed})

        # Process ACKs from Receiver
        for ack in self.input["ack_in"].values:
            if self.waiting_for_ack:
                self.waiting_for_ack = False
                self._write_event("ack_received_from_receiver", {"bit": ack["bit"]})
                # If download is now disabled, stop after this cycle
                if not self.download_allowed:
                    self.passivate("IDLE")
                else:
                    # If queue is not empty, send next packet
                    if self.packet_queue:
                        self.hold_in("SENDING_PACKET", 0.0)
                    else:
                        self.passivate("IDLE")
            else:
                # Late ACK - ignore or handle as needed
                self._write_event("ack_received_from_receiver", {"bit": ack["bit"]})

        # If we're not waiting for an ACK and have data to send, send it
        if not self.waiting_for_ack and self.download_allowed and self.packet_queue:
            self.hold_in("SENDING_PACKET", 0.0)
        elif not self.waiting_for_ack and self.download_allowed and not self.packet_queue:
            self.passivate("IDLE")
        else:
            self.continuef(e)

    def lambdaf(self):
        if self.phase == "SENDING_PACKET":
            packet = self.packet_queue.pop(0)
            self.output["data_out"].add(packet)
            self._write_event("packet_forwarded", packet)
            self.waiting_for_ack = True
        else:
            pass

    def deltint(self):
        if self.phase == "SENDING_PACKET":
            # Transition to waiting state after sending
            self.hold_in("WAITING_FOR_ACK", 0.0)
        elif self.phase == "WAITING_FOR_ACK":
            # This should not happen in normal operation since lambdaf handles the output
            # but keeping it for completeness
            if self.packet_queue:
                self.hold_in("SENDING_PACKET", 0.0)
            else:
                self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass