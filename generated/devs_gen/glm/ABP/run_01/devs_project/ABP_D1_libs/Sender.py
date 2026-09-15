import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """Implements the ABP Sender logic."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        total_packets: int,
        preparation_delay: float,
        timeout: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.total_packets = total_packets
        self.preparation_delay = preparation_delay
        self.timeout = timeout
        
        # Ports
        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "packet_out"))
        
        # Internal state
        self.seq_num = 1
        self.bit = 0
        self.is_retry = False
        self.waiting_for_ack = False

    def _write_event(self, event: str, payload: dict) -> None:
        """Helper to write JSONL records to stdout."""
        record = {
            "time": get_current_time(),
            "entity": "sender",
            "event": event,
            "payload": payload
        }
        print(json.dumps(record), flush=True)

    def _start_preparation(self) -> None:
        """Start the preparation delay and log the event."""
        self._write_event("delay_start", {
            "type": "preparation",
            "duration": self.preparation_delay
        })
        self.hold_in("PREPARING", self.preparation_delay)

    def initialize(self):
        """Initialize the Sender."""
        self.seq_num = 1
        self.bit = 0
        self.is_retry = False
        self.waiting_for_ack = False
        
        if self.total_packets > 0:
            self._start_preparation()
        else:
            self.passivate("DONE")

    def deltext(self, e: float):
        """Handle incoming ACKs."""
        ack_valid = False
        
        for ack in self.input["ack_in"].values:
            # Check if ACK matches the current expected bit
            received_bit = ack.get("ack_bit")
            is_valid = (received_bit == self.bit)
            
            self._write_event("ack_received", {
                "ack_bit": received_bit,
                "is_valid": is_valid
            })
            
            if is_valid:
                ack_valid = True

        if ack_valid:
            # Valid ACK received, advance to next packet
            self.waiting_for_ack = False
            self.is_retry = False
            self.seq_num += 1
            self.bit = 1 - self.bit  # Toggle bit
            
            if self.seq_num > self.total_packets:
                self.passivate("DONE")
            else:
                self._start_preparation()
        else:
            # Invalid ACK or no valid ACK, continue waiting (or preparing)
            # If we are currently preparing a retransmission (PREPARING phase),
            # the valid ACK would have cancelled it above. Since it wasn't valid,
            # we just continue the current phase.
            self.continuef(e)

    def lambdaf(self):
        """Emit the packet to the output port."""
        if self.phase == "OUTPUT_READY":
            payload = {
                "seq_num": self.seq_num,
                "bit": self.bit
            }
            self.output["packet_out"].add(payload)
            
            self._write_event("packet_sent", {
                "seq_num": self.seq_num,
                "bit": self.bit,
                "is_retry": self.is_retry
            })

    def deltint(self):
        """Handle internal transitions."""
        if self.phase == "PREPARING":
            # Preparation delay finished, schedule immediate output
            self.hold_in("OUTPUT_READY", 0.0)
            
        elif self.phase == "OUTPUT_READY":
            # Packet sent, start waiting for ACK (timer)
            self.waiting_for_ack = True
            self.hold_in("WAITING_FOR_ACK", self.timeout)
            
        elif self.phase == "WAITING_FOR_ACK":
            # Timer expired, start retransmission preparation
            self.is_retry = True
            self._start_preparation()
            
        else:
            # Should be DONE or passive
            self.passivate("DONE")

    def exit(self):
        pass