import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Receiver(Atomic):
    """Atomic DEVS model for the Receiver endpoint in Loop 2."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent
        
        # Ports
        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "ack_out"))
        
        # State variables
        self.current_packet = None
        self.queue = []
        self.payload_to_send = None
        
        # Constants
        self.PROCESSING_DELAY = 10000.0  # 10,000ms

    def _write_event(self, event_type: str, payload: dict) -> None:
        """Helper to write JSONL records to stdout."""
        record = {
            "timestamp_ms": get_current_time(),
            "model": "receiver",
            "type": event_type,
            "val": payload
        }
        print(json.dumps(record), flush=True)

    def initialize(self):
        self.current_packet = None
        self.queue = []
        self.payload_to_send = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # If we were processing, we need to preserve the remaining time
        if self.phase == "PROCESSING":
            self.continuef(e)
        
        # Handle incoming packets
        for packet in self.input["data_in"].values:
            if self.phase == "IDLE":
                # Start processing immediately
                self.current_packet = packet
                self._write_event("processing_started", {
                    "seq": packet["seq"],
                    "duration": int(self.PROCESSING_DELAY)
                })
                self.hold_in("PROCESSING", self.PROCESSING_DELAY)
            elif self.phase == "PROCESSING":
                # Buffer the packet if we are busy
                self.queue.append(packet)
            # If we are in OUTPUT_READY or other states, we buffer as well
            # to ensure we don't lose packets during the 0-time transition
            else:
                self.queue.append(packet)

    def lambdaf(self):
        if self.phase == "OUTPUT_READY" and self.payload_to_send is not None:
            self.output["ack_out"].add(self.payload_to_send)

    def deltint(self):
        if self.phase == "PROCESSING":
            # Processing delay elapsed
            bit = self.current_packet["bit"]
            self.payload_to_send = {"bit": bit}
            
            # Log the ACK sent event
            self._write_event("ack_sent", {"bit": bit})
            
            # Schedule output
            self.hold_in("OUTPUT_READY", 0.0)
            
        elif self.phase == "OUTPUT_READY":
            # Output done, reset current state
            self.current_packet = None
            self.payload_to_send = None
            
            # Check if there are queued packets
            if self.queue:
                next_packet = self.queue.pop(0)
                self.current_packet = next_packet
                self._write_event("processing_started", {
                    "seq": next_packet["seq"],
                    "duration": int(self.PROCESSING_DELAY)
                })
                self.hold_in("PROCESSING", self.PROCESSING_DELAY)
            else:
                self.passivate("IDLE")
        else:
            # Should not happen, but safe fallback
            self.passivate("IDLE")

    def exit(self):
        pass