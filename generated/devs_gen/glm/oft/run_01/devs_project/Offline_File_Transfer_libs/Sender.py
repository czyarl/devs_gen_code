"""Atomic DEVS model: Sender. Implements the Alternating Bit Protocol (ABP) for uploading."""

import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """Manages the upload queue and executes the Alternating Bit Protocol (ABP) to transmit packets to the Server."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Ports
        self.add_in_port(Port(int, "control_in"))
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "data_out"))

        # Internal State
        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0

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
        """Initialize in IDLE state."""
        self.packets_remaining = 0
        self.seq = 1
        self.bit = 0
        self.passivate("IDLE")

    def deltext(self, e: float):
        """Handle external inputs: control commands and ACKs."""
        # Handle control input
        for n in self.input["control_in"].values:
            if n > 0:
                self.packets_remaining += n
                self._write_event("control_cmd", {
                    "added": n,
                    "total_remaining": self.packets_remaining
                })
                if self.phase == "IDLE" and self.packets_remaining > 0:
                    # Transition to PREPARING immediately
                    self._write_event("preparation_started", {"duration": 10000})
                    self.hold_in("PREPARING", 10000.0)
                else:
                    # If already busy, just continue with current phase/time
                    self.continuef(e)

        # Handle ACK input
        for ack in self.input["ack_in"].values:
            ack_bit = ack.get("bit")
            # Only process ACK if we are waiting for one and the bit matches
            if self.phase == "WAITING_ACK" and ack_bit == self.bit:
                self._write_event("ack_received", {"bit": ack_bit})
                
                # Update state
                self.packets_remaining -= 1
                self.bit = 1 - self.bit  # Flip bit
                self.seq += 1

                # Determine next state
                if self.packets_remaining > 0:
                    # More packets to send: go to PREPARING
                    self._write_event("preparation_started", {"duration": 10000})
                    self.hold_in("PREPARING", 10000.0)
                else:
                    # All done: go to IDLE
                    self.passivate("IDLE")
            else:
                # Mismatched bit or not waiting: ignore, preserve phase
                if self.phase != "IDLE": 
                    self.continuef(e)

        # If no inputs triggered a state change (e.g. only control in active phase), ensure we continue
        # However, the logic above handles specific transitions. 
        # If we are in IDLE and receive no control, we stay passive.
        # If we are in WAITING_ACK and receive no valid ACK, we must continue waiting.
        if self.phase == "WAITING_ACK":
            self.continuef(e)
        elif self.phase == "PREPARING":
            self.continuef(e)

    def lambdaf(self):
        """Emit DEVS output when entering OUTPUT_READY."""
        if self.phase == "OUTPUT_READY":
            packet = {"seq": self.seq, "bit": self.bit}
            self.output["data_out"].add(packet)
            
            # Log packet sent
            # We need to know if this is a retry. 
            # We can infer retry status by checking if we are retransmitting the same seq/bit.
            # Since we only increment seq on success, if we are here, seq is the current one.
            # However, the contract says "is_retry" flag.
            # We can track a boolean self.is_retry in deltint.
            self._write_event("packet_sent", {
                "seq": self.seq,
                "bit": self.bit,
                "is_retry": self.is_retry
            })

    def deltint(self):
        """Handle internal transitions."""
        if self.phase == "PREPARING":
            # Preparation done, schedule output
            self.is_retry = False
            self.hold_in("OUTPUT_READY", 0.0)
        
        elif self.phase == "OUTPUT_READY":
            # Packet sent, start waiting for ACK
            self.hold_in("WAITING_ACK", 20000.0)
        
        elif self.phase == "WAITING_ACK":
            # Timeout occurred
            self._write_event("timeout", {"seq": self.seq})
            self.is_retry = True
            # Retransmit: go back to output immediately (no prep delay for retry)
            self.hold_in("OUTPUT_READY", 0.0)
        
        else:
            # Should not be reached if logic is correct, but passivate to be safe
            self.passivate("IDLE")

    def exit(self):
        pass