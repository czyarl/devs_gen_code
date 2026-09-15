"""ServerSender atomic DEVS model implementing download permission control and packet forwarding."""

import json
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ServerSender(Atomic):
    """Manages download permission control and forwards data packets from the storage queue to Receiver."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        # Internal state
        self.download_allowed = False
        self.storage_queue = deque()
        self.waiting_for_ack = False
        self.current_packet = None

        # Add input ports
        self.add_in_port(Port(dict, "download_valve"))
        self.add_in_port(Port(dict, "data"))
        self.add_in_port(Port(dict, "ack"))

        # Add output ports
        self.add_out_port(Port(dict, "data"))
        self.add_out_port(Port(dict, "ack"))

    def _write_event(self, event_type: str, payload: dict) -> None:
        """Write an event to stdout in the required JSONL format."""
        print(json.dumps({
            "timestamp_ms": get_current_time(),
            "model": "server_sender",
            "type": event_type,
            "val": payload,
        }), flush=True)

    def initialize(self):
        """Initialize the model state."""
        self.download_allowed = False
        self.storage_queue.clear()
        self.waiting_for_ack = False
        self.current_packet = None
        self.passivate("IDLE")

    def deltext(self, e):
        """Handle incoming events."""
        # Process download valve changes
        for valve_change in self.input["download_valve"].values:
            allowed = valve_change.get("allowed")
            self.download_allowed = allowed
            self._write_event("download_valve_change", {"allowed": allowed})

        # Process incoming data packets
        for data_packet in self.input["data"].values:
            self.storage_queue.append(data_packet)

        # Process ACKs from receiver
        for ack_packet in self.input["ack"].values:
            if self.waiting_for_ack and ack_packet.get("bit") == self.current_packet.get("bit"):
                self.waiting_for_ack = False
                self._write_event("ack_received_from_receiver", {"bit": ack_packet.get("bit")})
                # Emit ACK to server
                self.output["ack"].add(ack_packet)
                # If there's more data and download is allowed, proceed
                if self.storage_queue and self.download_allowed:
                    self.hold_in("SEND_PACKET", 0.0)
                else:
                    self.passivate("IDLE")
            else:
                # Late or incorrect ACK - ignore or handle as needed
                pass

        # Check if we should send a packet
        if not self.waiting_for_ack and self.storage_queue and self.download_allowed:
            self.hold_in("SEND_PACKET", 0.0)
        else:
            self.continuef(e)

    def lambdaf(self):
        """Output actions based on current phase."""
        if self.phase == "SEND_PACKET":
            if self.storage_queue and self.download_allowed:
                packet = self.storage_queue.popleft()
                self.output["data"].add(packet)
                self.current_packet = packet
                self.waiting_for_ack = True
                self._write_event("packet_forwarded", {
                    "seq": packet.get("seq"),
                    "bit": packet.get("bit")
                })
        elif self.phase == "OUTPUT_READY":
            self.output["data"].add(self.current_packet)
            self._write_event("packet_forwarded", {
                "seq": self.current_packet.get("seq"),
                "bit": self.current_packet.get("bit")
            })
            self.waiting_for_ack = True

    def deltint(self):
        """Internal transitions."""
        if self.phase == "SEND_PACKET":
            # We've already sent the packet in lambdaf(), now wait for ACK
            self.hold_in("WAITING_FOR_ACK", 0.0)
        elif self.phase == "WAITING_FOR_ACK":
            # If we are waiting for ACK and download is now disabled, stop
            if not self.download_allowed:
                self.passivate("IDLE")
            else:
                # If queue is not empty and download is allowed, continue sending
                if self.storage_queue:
                    self.hold_in("SEND_PACKET", 0.0)
                else:
                    self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        """Cleanup on model exit."""
        pass