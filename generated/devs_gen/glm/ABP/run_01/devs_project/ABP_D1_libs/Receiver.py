import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Receiver(Atomic):
    """Atomic DEVS model for the Receiver in the ABP system."""

    def __init__(self, name: str, parent: Coupled | None, processing_delay: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay = processing_delay
        
        # Ports
        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "ack_out"))
        
        # State variables
        self.current_packet = None  # The packet currently being processed
        self.waiting_buffer = None  # The single-slot waiting buffer
        self.ack_to_send = None     # ACK payload prepared for output

    def _write_event(self, event: str, payload: dict) -> None:
        """Helper to write JSONL records to stdout."""
        record = {
            "time": get_current_time(),
            "entity": "receiver",
            "event": event,
            "payload": payload
        }
        print(json.dumps(record), flush=True)

    def initialize(self):
        """Initialize the Receiver to IDLE state."""
        self.current_packet = None
        self.waiting_buffer = None
        self.ack_to_send = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        """Handle external transitions (incoming packets)."""
        # If we were processing, we need to preserve the remaining time.
        if self.phase == "BUSY":
            self.continuef(e)

        # Process all incoming packets
        for packet in self.input["packet_in"].values:
            if self.phase == "IDLE":
                # Transition to BUSY, store packet, start timer, log delay_start
                self.current_packet = packet
                self._write_event("delay_start", {
                    "type": "processing",
                    "duration": self.processing_delay
                })
                self.hold_in("BUSY", self.processing_delay)
            elif self.phase == "BUSY":
                # If buffer is empty, store the packet. If full, drop it.
                if self.waiting_buffer is None:
                    self.waiting_buffer = packet
                # else: drop packet (implicit no-op)

    def lambdaf(self):
        """Handle output function (send ACK)."""
        if self.phase == "SEND_ACK" and self.ack_to_send is not None:
            self.output["ack_out"].add(self.ack_to_send)

    def deltint(self):
        """Handle internal transitions (timer expiry)."""
        if self.phase == "BUSY":
            # Processing delay finished.
            # 1. Log packet_received
            self._write_event("packet_received", {
                "seq_num": self.current_packet["seq_num"],
                "bit": self.current_packet["bit"]
            })
            
            # 2. Prepare ACK for output
            self.ack_to_send = {"ack_bit": self.current_packet["bit"]}
            
            # 3. Schedule output immediately
            self.hold_in("SEND_ACK", 0.0)

        elif self.phase == "SEND_ACK":
            # ACK has been emitted in lambdaf. Now check buffer.
            self.current_packet = None
            self.ack_to_send = None
            
            if self.waiting_buffer is not None:
                # Move buffered packet to processing slot
                self.current_packet = self.waiting_buffer
                self.waiting_buffer = None
                
                # Log delay_start for the new packet
                self._write_event("delay_start", {
                    "type": "processing",
                    "duration": self.processing_delay
                })
                
                # Remain BUSY with new timer
                self.hold_in("BUSY", self.processing_delay)
            else:
                # No buffered packet, transition to IDLE
                self.passivate("IDLE")

    def exit(self):
        """Cleanup on simulation exit."""
        pass