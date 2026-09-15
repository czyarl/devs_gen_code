"""Atomic DEVS model for the Receiver in the ABP system."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Receiver(Atomic):
    """Simulates a destination for data packets in the Alternating Bit Protocol (ABP) system."""

    def __init__(self, name: str, parent: Coupled | None, receiver_delay: float):
        super().__init__(name)
        self.parent = parent
        self.receiver_delay = receiver_delay
        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "ack_out"))
        
        # Internal state variables
        self.current_packet = None
        self.waiting_buffer = None
        self.ack_payload = None

    def _write_event(self, event: str, payload: dict) -> None:
        """Helper to emit JSONL records to stdout."""
        record = {
            "time": get_current_time(),
            "entity": "receiver",
            "event": event,
            "payload": payload
        }
        print(json.dumps(record), flush=True)

    def _start_processing(self, packet: dict) -> None:
        """Start processing a packet and emit delay_start event."""
        self.current_packet = dict(packet)
        self._write_event("delay_start", {
            "type": "processing",
            "duration": self.receiver_delay
        })
        self.hold_in("PROCESSING", self.receiver_delay)

    def initialize(self):
        """Initialize the Receiver to an idle state."""
        self.current_packet = None
        self.waiting_buffer = None
        self.ack_payload = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        """Handle incoming packets from Subnet1."""
        was_processing = self.phase == "PROCESSING"
        if was_processing:
            # Preserve remaining time for the current processing phase
            self.continuef(e)

        for packet in self.input["packet_in"].values:
            if self.current_packet is None:
                # If idle, start processing immediately
                self._start_processing(packet)
            elif self.waiting_buffer is None:
                # If busy but buffer is empty, occupy the buffer slot
                self.waiting_buffer = dict(packet)
            # If buffer is full, the packet is dropped (implicit behavior)

    def lambdaf(self):
        """Emit the ACK packet when the processing delay expires."""
        if self.phase == "SEND_ACK" and self.ack_payload is not None:
            self.output["ack_out"].add(dict(self.ack_payload))

    def deltint(self):
        """Handle internal transitions: processing completion and ACK sending."""
        if self.phase == "PROCESSING":
            # Processing delay finished
            self._write_event("packet_received", {
                "seq_num": self.current_packet["seq_num"],
                "bit": self.current_packet["bit"]
            })
            
            # Prepare ACK payload
            self.ack_payload = {
                "ack_bit": self.current_packet["bit"]
            }
            
            # Schedule immediate output
            self.hold_in("SEND_ACK", 0.0)

        elif self.phase == "SEND_ACK":
            # ACK sent, clear current packet
            self.current_packet = None
            self.ack_payload = None
            
            # Check waiting buffer
            if self.waiting_buffer is not None:
                next_packet = self.waiting_buffer
                self.waiting_buffer = None
                self._start_processing(next_packet)
            else:
                # No buffered packet, return to idle
                self.passivate("IDLE")
        
        else:
            # Should not be reached, but passivate as a fallback
            self.passivate("IDLE")

    def exit(self):
        """Cleanup method."""
        pass