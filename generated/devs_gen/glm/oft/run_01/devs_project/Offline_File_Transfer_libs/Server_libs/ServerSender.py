import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ServerSender(Atomic):
    """
    Atomic DEVS model for ServerSender.
    Manages internal FIFO storage queue, download valve flag, and ABP protocol state
    to forward data packets to the Receiver.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        
        # Input Ports
        self.add_in_port(Port(bool, "request_in"))
        self.add_in_port(Port(dict, "ack_in"))
        self.add_in_port(Port(dict, "storage_in"))
        
        # Output Ports
        self.add_out_port(Port(dict, "data_out"))
        
        # Internal State
        self.queue = []
        self.download_allowed = False
        self.waiting_for_ack = False
        self.current_packet = None  # Stores the packet currently being sent (if waiting for ACK)
        
    def _write_event(self, event_type: str, payload: dict) -> None:
        """Helper to write JSONL records to stdout."""
        record = {
            "timestamp_ms": get_current_time(),
            "model": "server_sender",
            "type": event_type,
            "val": payload
        }
        print(json.dumps(record), flush=True)

    def initialize(self):
        """Initialize state: empty queue, valve closed, not waiting."""
        self.queue = []
        self.download_allowed = False
        self.waiting_for_ack = False
        self.current_packet = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        """Handle external inputs."""
        # 1. Handle Request (Download Valve)
        for request_val in self.input["request_in"].values:
            if request_val != self.download_allowed:
                self.download_allowed = request_val
                self._write_event("download_valve_change", {"allowed": self.download_allowed})

        # 2. Handle Storage In (Data to Queue)
        for packet in self.input["storage_in"].values:
            self.queue.append(packet)

        # 3. Handle ACK In
        ack_received = False
        for ack in self.input["ack_in"].values:
            if self.waiting_for_ack and self.current_packet:
                # Check if bit matches the sent packet
                if ack.get("bit") == self.current_packet.get("bit"):
                    self.waiting_for_ack = False
                    self.current_packet = None
                    self._write_event("ack_received_from_receiver", {"bit": ack.get("bit")})
                    ack_received = True
        
        # State Transition Logic
        if ack_received:
            # If we just received an ACK, check if we can send the next packet immediately.
            # According to R028 (No processing delay) and R029 (Conditions).
            if self._can_send():
                packet = self.queue.pop(0)
                self.current_packet = packet
                self.waiting_for_ack = True
                self._write_event("packet_forwarded", {"seq": packet["seq"], "bit": packet["bit"]})
                # Schedule immediate output
                self.hold_in("OUTPUT_READY", 0.0)
            else:
                self.passivate("IDLE")
        else:
            # If no ACK received (or we were idle), check if we can start sending.
            # Note: If we are currently waiting_for_ack, we ignore send triggers (R029/R030).
            if not self.waiting_for_ack and self._can_send():
                packet = self.queue.pop(0)
                self.current_packet = packet
                self.waiting_for_ack = True
                self._write_event("packet_forwarded", {"seq": packet["seq"], "bit": packet["bit"]})
                self.hold_in("OUTPUT_READY", 0.0)
            else:
                # Preserve phase if active, or passivate if idle.
                if self.phase == "IDLE":
                    self.passivate("IDLE")
                else:
                    # We are waiting for ACK, just continue waiting.
                    self.continuef(e)

    def _can_send(self) -> bool:
        """Check conditions for sending: valve open, queue not empty, not waiting."""
        return self.download_allowed and len(self.queue) > 0 and not self.waiting_for_ack

    def lambdaf(self):
        """Emit DEVS output."""
        if self.phase == "OUTPUT_READY" and self.current_packet:
            self.output["data_out"].add(self.current_packet)

    def deltint(self):
        """Handle internal transitions."""
        if self.phase == "OUTPUT_READY":
            # Output is done. Now we wait for ACK.
            # Since ABP has no timeout specified for ServerSender (unlike Sender), 
            # we wait indefinitely until ACK arrives via deltext.
            self.passivate("WAITING_ACK")
        else:
            # Should not reach here if logic is correct, but passivate to be safe.
            self.passivate("IDLE")

    def exit(self):
        pass