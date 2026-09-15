import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """Atomic DEVS model implementing the Upload ABP logic."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Ports
        self.add_in_port(Port(dict, "control_in"))
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "data_out"))

        # State variables
        self.packets_remaining = 0
        self.sequence = 1
        self.bit = 0
        self.is_retry = False

    def _write_event(self, event_type: str, payload: dict) -> None:
        """Helper to write JSONL records to stdout."""
        record = {
            "timestamp_ms": get_current_time(),
            "model": "sender",
            "type": event_type,
            "val": payload
        }
        print(json.dumps(record), flush=True)

    def initialize(self):
        """Initialize the model."""
        # Initialize with sequence number 1, alternating bit 0, and 0 packets remaining.
        self.packets_remaining = 0
        self.sequence = 1
        self.bit = 0
        self.is_retry = False
        
        # Start in idle state
        self.passivate("idle")

    def deltext(self, e: float):
        """Handle external transitions."""
        control_processed = False
        ack_processed = False

        # Handle control_in
        if not self.input["control_in"].empty():
            for cmd in self.input["control_in"].values:
                added = cmd.get("added", 0)
                total = cmd.get("total_remaining", 0)
                
                # Update packet count
                self.packets_remaining = total
                
                # Log control_cmd event
                self._write_event("control_cmd", {
                    "added": added,
                    "total_remaining": self.packets_remaining
                })
                control_processed = True

        # Handle ack_in
        if not self.input["ack_in"].empty():
            for ack in self.input["ack_in"].values:
                # Only process ACKs if we are in waiting state
                if self.phase == "waiting":
                    received_bit = ack.get("bit")
                    
                    # Check if the bit matches the current expected bit
                    if received_bit == self.bit:
                        # Log ack_received
                        self._write_event("ack_received", {"bit": self.bit})
                        
                        # Decrement remaining packets
                        if self.packets_remaining > 0:
                            self.packets_remaining -= 1
                        
                        # Flip the bit and increment sequence
                        self.bit = 1 - self.bit
                        self.sequence += 1
                        self.is_retry = False
                        
                        ack_processed = True
                    else:
                        # Mismatched bit (duplicate ACK), ignore and stay in waiting
                        # The timeout will handle retransmission if necessary
                        pass

        # State transition logic
        if ack_processed:
            # If we processed a valid ACK, transition to next state
            if self.packets_remaining > 0:
                # Start preparing next packet
                self._write_event("preparation_started", {"duration": 10000})
                self.hold_in("preparing", 10000.0)
            else:
                # No more packets, go idle
                self.passivate("idle")
        elif control_processed:
            # If we processed a control command
            if self.phase == "idle" and self.packets_remaining > 0:
                # Wake up and start preparing
                self._write_event("preparation_started", {"duration": 10000})
                self.hold_in("preparing", 10000.0)
            else:
                # If already busy, just continue with current phase
                self.continuef(e)
        else:
            # No relevant input processed
            self.continuef(e)

    def lambdaf(self):
        """Handle output function."""
        if self.phase == "sending":
            # Send data_out with current sequence and bit
            packet = {
                "seq": self.sequence,
                "bit": self.bit
            }
            self.output["data_out"].add(packet)
            
            # Log packet_sent
            self._write_event("packet_sent", {
                "seq": self.sequence,
                "bit": self.bit,
                "is_retry": self.is_retry
            })

    def deltint(self):
        """Handle internal transitions."""
        if self.phase == "preparing":
            # Preparation done, schedule send
            self.hold_in("sending", 0.0)
        
        elif self.phase == "sending":
            # Packet sent, start waiting for ACK
            self.hold_in("waiting", 20000.0)
        
        elif self.phase == "waiting":
            # Timeout expired
            # Log timeout
            self._write_event("timeout", {"seq": self.sequence})
            
            # Mark as retry and retransmit
            self.is_retry = True
            
            # Go back to preparing state to retransmit (or sending if we want immediate)
            # The contract says "retransmit via data_out", which implies sending immediately.
            # However, standard DEVS usually separates output and transition.
            # Let's schedule a send immediately.
            self.hold_in("sending", 0.0)
        
        else:
            # Should not reach here for idle or passive states without external input
            self.passivate("idle")

    def exit(self):
        """Cleanup on exit."""
        pass