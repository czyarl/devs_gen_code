"""Sender atomic DEVS model implementing the Alternating Bit Protocol."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """Sender model for the Alternating Bit Protocol simulation."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        total_packets: int,
        sender_delay: float,
        timeout: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.total_packets = total_packets
        self.sender_delay = sender_delay
        self.timeout = timeout
        
        # Initialize ports as per contract
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "delay_start"))
        self.add_out_port(Port(dict, "packet_sent"))
        self.add_out_port(Port(dict, "ack_received"))
        
        # Model state
        self.current_seq = 1
        self.current_bit = 0
        self.is_retry = False
        self.outstanding = False
        self.timer_active = False

    def _write_event(self, event: str, payload: dict) -> None:
        """Write a JSONL event record to stdout."""
        print(json.dumps({
            "time": get_current_time(),
            "entity": "sender",
            "event": event,
            "payload": payload,
        }), flush=True)

    def _send_delay_start(self) -> None:
        """Emit delay_start event when preparation begins."""
        payload = {"type": "preparation", "duration": self.sender_delay}
        self.output["delay_start"].add(payload)
        self._write_event("delay_start", payload)

    def _send_packet(self) -> None:
        """Emit packet_sent event when packet is sent."""
        payload = {
            "seq_num": self.current_seq,
            "bit": self.current_bit,
            "is_retry": self.is_retry
        }
        self.output["packet_sent"].add(payload)
        self._write_event("packet_sent", payload)

    def _send_ack_received(self, ack_bit: int, is_valid: bool) -> None:
        """Emit ack_received event when ACK is received."""
        payload = {"ack_bit": ack_bit, "is_valid": is_valid}
        self.output["ack_received"].add(payload)
        self._write_event("ack_received", payload)

    def initialize(self):
        """Initialize the Sender model."""
        self.current_seq = 1
        self.current_bit = 0
        self.is_retry = False
        self.outstanding = False
        self.timer_active = False
        
        # Start the first preparation delay immediately
        self._send_delay_start()
        self.hold_in("PREPARING", self.sender_delay)

    def deltext(self, e):
        """Handle external inputs."""
        feedback_received = False
        for ack in self.input["ack_in"].values:
            ack_bit = ack.get("ack_bit")
            is_valid = self.outstanding and ack_bit == self.current_bit
            
            self._send_ack_received(ack_bit, is_valid)
            feedback_received = True
            
            if is_valid:
                # Valid ACK received; cancel outstanding and advance
                self.outstanding = False
                self.timer_active = False
                self.is_retry = False
                self.current_seq += 1
                
                if self.current_seq > self.total_packets:
                    # All packets sent; terminate
                    self.passivate("DONE")
                else:
                    # Prepare next packet
                    self.current_bit = 1 - self.current_bit  # Toggle bit
                    self._send_delay_start()
                    self.hold_in("PREPARING", self.sender_delay)
                return
        
        if not feedback_received:
            # No feedback was processed; continue with current phase
            self.continuef(e)

    def lambdaf(self):
        """Handle output events."""
        if self.phase == "OUTPUT_READY":
            self._send_packet()
        elif self.phase == "WAITING_FOR_ACK":
            # This should not happen in lambdaf, but included for completeness
            pass

    def deltint(self):
        """Handle internal transitions."""
        if self.phase == "PREPARING":
            # Preparation complete; ready to send packet
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase == "OUTPUT_READY":
            # Packet sent; start timeout timer
            self.outstanding = True
            self.timer_active = True
            self.hold_in("WAITING_FOR_ACK", self.timeout)
        elif self.phase == "WAITING_FOR_ACK":
            # Timeout occurred; retransmit packet
            self.is_retry = True
            self._send_delay_start()
            self.hold_in("PREPARING", self.sender_delay)
        else:
            self.passivate("DONE")

    def exit(self):
        """Clean up resources."""
        pass