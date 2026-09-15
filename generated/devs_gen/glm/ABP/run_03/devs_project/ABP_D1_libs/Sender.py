import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """Atomic DEVS model for the Sender in the ABP system."""

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
        
        # State variables
        self.current_seq_num = 1
        self.current_bit = 0
        self.is_retry = False
        self.packet_outstanding = False

    def _write_event(self, event: str, payload: dict) -> None:
        """Helper to write JSONL events to stdout."""
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
        """Initialize the Sender state."""
        self.current_seq_num = 1
        self.current_bit = 0
        self.is_retry = False
        self.packet_outstanding = False
        
        if self.total_packets > 0:
            self._start_preparation()
        else:
            self.passivate("DONE")

    def deltext(self, e):
        """Handle incoming ACKs."""
        ack_accepted = False
        
        # Process all ACKs on the port
        for ack in self.input["ack_in"].values:
            ack_bit = ack.get("bit")
            
            # Determine validity based on current expected bit
            # Note: Even if not outstanding, we check validity for logging,
            # but we only advance if outstanding and valid.
            is_valid = (ack_bit == self.current_bit)
            
            self._write_event("ack_received", {
                "ack_bit": ack_bit,
                "is_valid": is_valid
            })
            
            if self.packet_outstanding and is_valid:
                ack_accepted = True

        if ack_accepted:
            # Valid ACK received: advance to next packet
            self.packet_outstanding = False
            self.is_retry = False
            self.current_seq_num += 1
            self.current_bit = 1 - self.current_bit  # Toggle bit (0 -> 1, 1 -> 0)
            
            if self.current_seq_num > self.total_packets:
                self.passivate("DONE")
            else:
                self._start_preparation()
        else:
            # No valid ACK processed, continue waiting or preparing
            # If we are preparing and get a late ACK, deltext handles it.
            # If we are waiting, we just continue waiting.
            self.continuef(e)

    def lambdaf(self):
        """Emit the packet when the internal transition fires."""
        if self.phase == "OUTPUT_READY":
            packet = {
                "seq_num": self.current_seq_num,
                "bit": self.current_bit
            }
            self.output["packet_out"].add(packet)
            
            self._write_event("packet_sent", {
                "seq_num": self.current_seq_num,
                "bit": self.current_bit,
                "is_retry": self.is_retry
            })

    def deltint(self):
        """Handle internal state transitions."""
        if self.phase == "PREPARING":
            # Preparation delay finished, schedule output immediately
            self.hold_in("OUTPUT_READY", 0.0)
            
        elif self.phase == "OUTPUT_READY":
            # Packet emitted, start waiting for ACK
            self.packet_outstanding = True
            self.hold_in("WAITING_FOR_ACK", self.timeout)
            
        elif self.phase == "WAITING_FOR_ACK":
            # Timeout expired, trigger retransmission
            self.is_retry = True
            # Retransmission requires preparation delay again
            self._start_preparation()
            
        else:
            # Should be DONE or passive
            self.passivate("DONE")

    def exit(self):
        """Cleanup on simulation exit."""
        pass