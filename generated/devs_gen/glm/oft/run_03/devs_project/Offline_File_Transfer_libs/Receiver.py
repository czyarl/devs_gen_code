from xdevs.models import Atomic, Coupled, Port
import json
from devs_project.devs_utils.devs_context import get_current_time


class Receiver(Atomic):
    """Atomic DEVS model for the Receiver in the Alternating Bit Protocol (Loop 2).

    Implements a single-in-flight service with a fixed 10,000ms processing delay.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Ports
        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "ack_out"))

        # Internal State
        self.current_seq = None
        self.current_bit = None

    def initialize(self):
        """Initialize the model in an IDLE state."""
        self.current_seq = None
        self.current_bit = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        """Handle external input on data_in."""
        if self.phase == "IDLE":
            # Check for incoming data
            if not self.input["data_in"].empty():
                # Get the packet
                packet = self.input["data_in"].get()
                
                # Store packet info
                self.current_seq = packet.get("seq")
                self.current_bit = packet.get("bit")

                # Log processing_started
                self._log_processing_started()

                # Schedule internal transition for 10,000ms
                self.hold_in("PROCESSING", 10000.0)
            else:
                self.passivate("IDLE")
        elif self.phase == "PROCESSING":
            # Ignore incoming packets while processing (single-in-flight constraint)
            self.continuef(e)
        else:
            self.passivate("IDLE")

    def lambdaf(self):
        """Emit output on ack_out when internal event fires."""
        if self.phase == "PROCESSING" and self.current_bit is not None:
            # Prepare ACK payload
            ack_payload = {"bit": self.current_bit}
            self.output["ack_out"].add(ack_payload)

    def deltint(self):
        """Handle internal transition after processing delay."""
        if self.phase == "PROCESSING":
            # Log ack_sent
            self._log_ack_sent()

            # Reset state and return to IDLE
            self.current_seq = None
            self.current_bit = None
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        """Cleanup on simulation exit."""
        pass

    def _log_processing_started(self):
        """Write 'processing_started' JSONL record to stdout."""
        record = {
            "timestamp_ms": get_current_time(),
            "model": "receiver",
            "type": "processing_started",
            "val": {
                "seq": self.current_seq,
                "duration": 10000
            }
        }
        print(json.dumps(record), flush=True)

    def _log_ack_sent(self):
        """Write 'ack_sent' JSONL record to stdout."""
        record = {
            "timestamp_ms": get_current_time(),
            "model": "receiver",
            "type": "ack_sent",
            "val": {
                "bit": self.current_bit
            }
        }
        print(json.dumps(record), flush=True)