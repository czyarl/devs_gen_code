import json
from collections import deque
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ServerSender(Atomic):
    """
    Implements the egress ABP logic for the ServerSender.
    Manages the download side of the server, forwarding data packets from an
    internal storage queue to a Receiver via SubnetB.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Input Ports
        self.add_in_port(Port(dict, "request_in"))
        self.add_in_port(Port(dict, "storage_in"))
        self.add_in_port(Port(dict, "ack_in"))

        # Output Ports
        self.add_out_port(Port(dict, "data_out"))

        # Internal State
        self.download_allowed: bool = False
        self.storage_queue: deque = deque()
        self.waiting_for_ack: bool = False
        self.current_packet: dict | None = None
        self.expected_ack_bit: int = 0  # Not strictly used for ABP logic here, but good for tracking

        # Phase management
        # Phases:
        # "IDLE": Waiting for conditions to send (valve open, queue not empty)
        # "SENDING": Zero-delay phase to emit the packet
        # "WAITING_ACK": Waiting for ACK from Receiver
        self.phase = "IDLE"
        self.sigma = float('inf')

    def _write_event(self, event_type: str, val: dict) -> None:
        """Helper to write JSONL records to stdout."""
        record = {
            "timestamp_ms": get_current_time(),
            "model": "server_sender",
            "type": event_type,
            "val": val
        }
        print(json.dumps(record), flush=True)

    def initialize(self):
        """Initialize the model state."""
        self.download_allowed = False
        self.storage_queue.clear()
        self.waiting_for_ack = False
        self.current_packet = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        """Handle external input events."""
        state_changed = False

        # 1. Handle Request Input (Valve Control)
        if not self.input["request_in"].empty():
            for req in self.input["request_in"].values:
                # Structure: {'allowed': bool}
                new_allowed = req.get("allowed")
                if new_allowed is not None and new_allowed != self.download_allowed:
                    self.download_allowed = new_allowed
                    self._write_event("download_valve_change", {"allowed": self.download_allowed})
                    state_changed = True

        # 2. Handle Storage Input (Data from ServerReceiver)
        if not self.input["storage_in"].empty():
            for pkt in self.input["storage_in"].values:
                # Structure: {'seq': int, 'bit': 0|1}
                self.storage_queue.append(pkt)
                # If we were idle and conditions are now met, we might trigger a send immediately.
                # However, we check conditions at the end of deltext or in deltint.
                # If we are waiting for ACK, we just queue it.

        # 3. Handle ACK Input
        if not self.input["ack_in"].empty():
            for ack in self.input["ack_in"].values:
                # Structure: {'bit': 0|1}
                ack_bit = ack.get("bit")
                self._write_event("ack_received_from_receiver", {"bit": ack_bit})

                if self.waiting_for_ack and self.current_packet:
                    # Check if ACK matches the packet we sent
                    # ABP Logic: If bit matches, transfer complete.
                    if ack_bit == self.current_packet.get("bit"):
                        self.waiting_for_ack = False
                        self.current_packet = None
                        state_changed = True
                    # If bit does not match, it's a duplicate ACK for previous packet.
                    # We ignore it and keep waiting for the correct ACK or timeout (if timeout existed).
                    # Note: The requirements don't specify a timeout for ServerSender ABP, 
                    # but implies waiting for ACK. We rely on the Receiver eventually sending the right ACK.
        
        # State Transition Logic
        if state_changed:
            if not self.waiting_for_ack:
                # If we just finished an ACK cycle, check if we can send the next one
                if self.download_allowed and self.storage_queue:
                    # Prepare to send immediately
                    self.current_packet = self.storage_queue.popleft()
                    self.waiting_for_ack = True
                    self.hold_in("SENDING", 0.0)
                else:
                    self.passivate("IDLE")
            else:
                # We are still waiting for ACK, or we just received a duplicate ACK
                # If we are in IDLE but received storage input and valve is open, we should send.
                # However, if waiting_for_ack is True, we must be in WAITING_ACK phase.
                # If waiting_for_ack is False, we are in IDLE.
                
                # If we are IDLE and conditions are met, start sending.
                if self.phase == "IDLE" and self.download_allowed and self.storage_queue:
                    self.current_packet = self.storage_queue.popleft()
                    self.waiting_for_ack = True
                    self.hold_in("SENDING", 0.0)
                else:
                    # Preserve remaining time if we were in a phase (e.g. WAITING_ACK)
                    if self.phase == "WAITING_ACK":
                        self.continuef(e)
                    elif self.phase == "IDLE":
                        self.passivate("IDLE")
        else:
            # No state change logic triggered by inputs (e.g. just storage added while waiting)
            if self.phase == "IDLE" and self.download_allowed and self.storage_queue:
                self.current_packet = self.storage_queue.popleft()
                self.waiting_for_ack = True
                self.hold_in("SENDING", 0.0)
            else:
                self.continuef(e)

    def lambdaf(self):
        """Emit output when in SENDING phase."""
        if self.phase == "SENDING" and self.current_packet:
            self.output["data_out"].add(self.current_packet)
            self._write_event("packet_forwarded", {
                "seq": self.current_packet.get("seq"),
                "bit": self.current_packet.get("bit")
            })

    def deltint(self):
        """Handle internal transitions."""
        if self.phase == "SENDING":
            # Packet has been sent, now wait for ACK
            # Since there is no timeout specified in requirements for ServerSender (unlike Sender),
            # we wait indefinitely until ACK arrives.
            self.hold_in("WAITING_ACK", float('inf'))
        elif self.phase == "WAITING_ACK":
            # This state is left only by deltext (receiving ACK)
            # If we somehow timeout (not specified), we would retry.
            # For now, this shouldn't be reached unless we implement timeout.
            # Based on requirements, we just wait.
            pass
        else:
            self.passivate("IDLE")

    def exit(self):
        pass