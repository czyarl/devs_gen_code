import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """Implements the Uploader ABP logic for the Sender model."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        preparation_delay: float,
        timeout: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.preparation_delay = preparation_delay
        self.timeout = timeout

        # Initialize ports
        self.add_in_port(Port(int, "control_in"))
        self.add_in_port(Port(int, "ack_in"))
        self.add_out_port(Port(dict, "data_out"))

        # State variables
        self.packets_remaining = 0
        self.current_seq = 1
        self.current_bit = 0
        self.is_retry = False

    def _write_event(self, event_type: str, val: dict) -> None:
        """Writes a JSONL record to stdout."""
        record = {
            "timestamp_ms": get_current_time(),
            "model": "sender",
            "type": event_type,
            "val": val
        }
        print(json.dumps(record), flush=True)

    def initialize(self):
        """Initialize the model state."""
        self.packets_remaining = 0
        self.current_seq = 1
        self.current_bit = 0
        self.is_retry = False
        self.passivate("IDLE")

    def deltext(self, e):
        """Handle external inputs."""
        control_received = False
        ack_received = False
        ack_bit = None

        # Process control_in
        if not self.input["control_in"].empty():
            for n in self.input["control_in"].values:
                self.packets_remaining += n
                self._write_event("control_cmd", {"added": n, "total_remaining": self.packets_remaining})
                control_received = True

        # Process ack_in
        if not self.input["ack_in"].empty():
            for bit in self.input["ack_in"].values:
                ack_bit = bit
                ack_received = True

        # State transitions based on inputs and current phase
        if self.phase == "IDLE":
            if control_received and self.packets_remaining > 0:
                # Transition from Idle to Preparation
                self._write_event("preparation_started", {"duration": self.preparation_delay})
                self.hold_in("PREPARING", self.preparation_delay)
            else:
                self.continuef(e)
        
        elif self.phase == "PREPARING":
            # If control arrives during preparation, just extend count, continue preparing
            self.continuef(e)

        elif self.phase == "WAITING_FOR_ACK":
            if ack_received:
                if ack_bit == self.current_bit:
                    # Valid ACK
                    self._write_event("ack_received", {"bit": self.current_bit})
                    
                    # Update state
                    self.current_bit = 1 - self.current_bit
                    self.current_seq += 1
                    self.packets_remaining -= 1
                    self.is_retry = False

                    if self.packets_remaining > 0:
                        # Immediately send next packet (schedule output)
                        self.hold_in("SENDING", 0.0)
                    else:
                        # Return to Idle
                        self.passivate("IDLE")
                else:
                    # Invalid/Unexpected ACK (e.g. duplicate ACK for previous packet)
                    # According to standard ABP, we ignore it and keep waiting for timeout or correct ACK
                    self.continuef(e)
            
            elif control_received:
                # Control arrived while waiting for ACK, just extend queue
                self.continuef(e)
            
            else:
                self.continuef(e)

        elif self.phase == "SENDING":
            # If we are in a zero-delay sending phase and receive input, 
            # usually deltcon handles this, but if deltext is called separately:
            # We prioritize finishing the send logic in deltint/lambdaf
            # However, if control comes in here, we just update the counter.
            self.continuef(e)

        else:
            self.continuef(e)

    def lambdaf(self):
        """Generate outputs."""
        if self.phase == "SENDING":
            packet = {'seq': self.current_seq, 'bit': self.current_bit}
            self.output["data_out"].add(packet)
            self._write_event("packet_sent", {"seq": self.current_seq, "bit": self.current_bit, "is_retry": self.is_retry})

    def deltint(self):
        """Handle internal transitions."""
        if self.phase == "PREPARING":
            # Preparation finished, send packet immediately
            self.is_retry = False
            self.hold_in("SENDING", 0.0)

        elif self.phase == "SENDING":
            # Packet sent, start waiting for ACK
            self.hold_in("WAITING_FOR_ACK", self.timeout)

        elif self.phase == "WAITING_FOR_ACK":
            # Timeout expired
            self._write_event("timeout", {"seq": self.current_seq})
            self.is_retry = True
            # Retransmit: go back to sending phase
            self.hold_in("SENDING", 0.0)

        else:
            # Should not be reached if logic is correct, but safe fallback
            if self.packets_remaining > 0:
                self.hold_in("PREPARING", self.preparation_delay)
            else:
                self.passivate("IDLE")

    def exit(self):
        pass