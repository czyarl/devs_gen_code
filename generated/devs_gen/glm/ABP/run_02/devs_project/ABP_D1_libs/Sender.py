import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Sender(Atomic):
    """Autonomous source of data packets using Stop-and-Wait logic."""

    def __init__(
        self,
        name: str,
        parent: Coupled | None,
        total_packets: int,
        timeout: float,
        sender_delay: float,
    ):
        super().__init__(name)
        self.parent = parent
        self.total_packets = total_packets
        self.timeout = timeout
        self.sender_delay = sender_delay

        self.add_in_port(Port(dict, "ack_in"))
        self.add_out_port(Port(dict, "packet_out"))

        # State variables
        self.seq_num = 1
        self.bit = 0
        self.is_retry = False
        self.outstanding = False

    def _write_event(self, event: str, payload: dict) -> None:
        """Helper to write JSONL records to stdout."""
        print(json.dumps({
            "time": get_current_time(),
            "entity": "sender",
            "event": event,
            "payload": payload,
        }), flush=True)

    def _begin_preparation(self) -> None:
        """Start the preparation delay and log the event."""
        self._write_event("delay_start", {
            "type": "preparation",
            "duration": self.sender_delay,
        })
        self.hold_in("PREPARING", self.sender_delay)

    def initialize(self):
        """Initialize state and start the first preparation delay."""
        self.seq_num = 1
        self.bit = 0
        self.is_retry = False
        self.outstanding = False

        if self.total_packets > 0:
            self._begin_preparation()
        else:
            self.passivate("DONE")

    def deltext(self, e):
        """Handle incoming ACKs."""
        accepted = False
        for ack in self.input["ack_in"].values:
            ack_bit = ack.get("ack_bit")
            # Validate ACK: must match current control bit
            is_valid = self.outstanding and (ack_bit == self.bit)
            
            self._write_event("ack_received", {
                "ack_bit": ack_bit,
                "is_valid": is_valid,
            })
            
            accepted = accepted or is_valid

        if accepted:
            # Valid ACK received: cancel any pending retransmission, advance state
            self.outstanding = False
            self.is_retry = False
            self.seq_num += 1
            self.bit = 1 - self.bit  # Toggle control bit

            if self.seq_num > self.total_packets:
                self.passivate("DONE")
            else:
                self._begin_preparation()
        else:
            # Invalid ACK or no valid ACK: continue current phase
            # If we were preparing a retransmission, we stay in PREPARING.
            # If we were waiting for ACK, we stay in WAITING.
            self.continuef(e)

    def lambdaf(self):
        """Emit the packet to the output port."""
        if self.phase == "OUTPUT_READY":
            packet = {
                "seq_num": self.seq_num,
                "bit": self.bit
            }
            self.output["packet_out"].add(packet)
            self._write_event("packet_sent", {
                "seq_num": self.seq_num,
                "bit": self.bit,
                "is_retry": self.is_retry,
            })

    def deltint(self):
        """Handle internal transitions (preparation done, timeout)."""
        if self.phase == "PREPARING":
            # Preparation finished; schedule immediate output
            self.hold_in("OUTPUT_READY", 0.0)
        elif self.phase == "OUTPUT_READY":
            # Packet sent; start waiting for ACK (timer)
            self.outstanding = True
            self.hold_in("WAITING", self.timeout)
        elif self.phase == "WAITING":
            # Timer expired; start retransmission preparation
            self.is_retry = True
            self._begin_preparation()
        else:
            # Should not be reached if logic is correct, but passivate just in case
            self.passivate("DONE")

    def exit(self):
        pass