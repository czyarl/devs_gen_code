import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ServerReceiver(Atomic):
    """Atomic DEVS model for the Server Receiver (Ingress Logic)."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "ack_out"))
        self.add_out_port(Port(dict, "storage_out"))
        
        # State variables
        self.expected_bit = 0
        self.current_packet = None
        self.waiting_packet = None
        self.ack_to_send = None
        self.storage_to_send = None
        
        # Constants
        self.PROCESSING_DELAY = 3000.0  # 3 seconds in milliseconds

    def _log_event(self, event_type: str, val: dict) -> None:
        """Helper to write JSONL events to stdout."""
        record = {
            "timestamp_ms": get_current_time(),
            "model": "server_receiver",
            "type": event_type,
            "val": val
        }
        print(json.dumps(record), flush=True)

    def initialize(self):
        self.expected_bit = 0
        self.current_packet = None
        self.waiting_packet = None
        self.ack_to_send = None
        self.storage_to_send = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # If we are currently processing a packet, we continue processing
        # and reduce the remaining time sigma by e.
        if self.phase == "PROCESSING":
            self.continuef(e)
        
        # Handle incoming packets
        for packet in self.input["data_in"].values:
            # Log packet received immediately upon arrival
            self._log_event("packet_received", {
                "seq": packet["seq"],
                "bit": packet["bit"]
            })

            if self.current_packet is None:
                # Start processing this packet
                self.current_packet = packet
                self.hold_in("PROCESSING", self.PROCESSING_DELAY)
            elif self.waiting_packet is None:
                # Buffer one packet if busy
                self.waiting_packet = packet
            # If both slots full, packet is dropped (implicit behavior based on queue size)

    def lambdaf(self):
        # Emit ACK when output is ready
        if self.phase == "OUTPUT_READY" and self.ack_to_send is not None:
            self.output["ack_out"].add(self.ack_to_send)
            
            # Emit to storage if valid (not a duplicate)
            if self.storage_to_send is not None:
                self.output["storage_out"].add(self.storage_to_send)

    def deltint(self):
        if self.phase == "PROCESSING":
            # Processing delay finished. Determine logic based on bit comparison.
            packet_bit = self.current_packet["bit"]
            
            if packet_bit == self.expected_bit:
                # Valid packet
                self.ack_to_send = {"bit": self.expected_bit}
                self.storage_to_send = {
                    "seq": self.current_packet["seq"],
                    "bit": self.current_packet["bit"]
                }
                # Flip expected bit for next packet
                self.expected_bit = 1 - self.expected_bit
            else:
                # Duplicate packet
                self.ack_to_send = {"bit": self.expected_bit}
                self.storage_to_send = None  # Do not forward to storage

            # Log the ACK sending event
            self._log_event("ack_sent_to_sender", {"bit": self.ack_to_send["bit"]})
            
            # Schedule output immediately
            self.hold_in("OUTPUT_READY", 0.0)
            
        elif self.phase == "OUTPUT_READY":
            # Output sent, clear current state
            self.current_packet = None
            self.ack_to_send = None
            self.storage_to_send = None
            
            # Check if there is a waiting packet
            if self.waiting_packet is not None:
                self.current_packet = self.waiting_packet
                self.waiting_packet = None
                self.hold_in("PROCESSING", self.PROCESSING_DELAY)
            else:
                self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass