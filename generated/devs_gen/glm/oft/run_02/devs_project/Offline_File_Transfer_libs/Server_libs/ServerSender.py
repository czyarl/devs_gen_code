import json
import sys
from collections import deque

from xdevs.models import Atomic, Coupled, Port

from devs_project.devs_utils.devs_context import get_current_time


class ServerSender(Atomic):
    """
    Atomic model managing the download valve and implementing the server-side
    Alternating Bit Protocol (ABP) for the transfer loop to the Receiver.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Input Ports
        self.add_in_port(Port(int, "request_in"))
        self.add_in_port(Port(dict, "storage_in"))
        self.add_in_port(Port(int, "ack_in"))

        # Output Ports
        self.add_out_port(Port(dict, "data_out"))

        # Internal State
        self.download_allowed = False
        self.storage_queue = deque()
        self.expected_bit = 0
        self.waiting_for_ack = False
        self.current_packet = None  # Stores the packet currently being sent/waiting for ACK

    def initialize(self):
        """Initialize the model state."""
        self.download_allowed = False
        self.storage_queue.clear()
        self.expected_bit = 0
        self.waiting_for_ack = False
        self.current_packet = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        """Handle external inputs."""
        request_changed = False

        # 1. Process request_in (Download Valve)
        if not self.input["request_in"].empty():
            for val in self.input["request_in"].values:
                if self.download_allowed != bool(val):
                    self.download_allowed = bool(val)
                    request_changed = True
                    # Log download_valve_change
                    print(json.dumps({
                        "timestamp_ms": get_current_time(),
                        "model": "server_sender",
                        "type": "download_valve_change",
                        "val": {"allowed": self.download_allowed}
                    }), flush=True)

        # 2. Process storage_in (Data from ServerReceiver)
        if not self.input["storage_in"].empty():
            for packet in self.input["storage_in"].values:
                self.storage_queue.append(packet)

        # 3. Process ack_in (ACK from Receiver)
        if not self.input["ack_in"].empty():
            for ack_bit in self.input["ack_in"].values:
                if self.waiting_for_ack:
                    # Check if ACK matches the bit of the packet we are waiting for
                    # ABP Logic: We expect an ACK for the bit we just sent.
                    if ack_bit == self.current_packet['bit']:
                        # Log ack_received_from_receiver
                        print(json.dumps({
                            "timestamp_ms": get_current_time(),
                            "model": "server_sender",
                            "type": "ack_received_from_receiver",
                            "val": {"bit": ack_bit}
                        }), flush=True)

                        # Flip expected bit for the *next* packet sequence logic if needed,
                        # though here we just clear waiting state.
                        # The ABP state machine implies we toggle the bit we are interested in
                        # or simply acknowledge the current one is done.
                        # Based on requirements: "flips the expected bit"
                        self.expected_bit = 1 - self.expected_bit
                        self.waiting_for_ack = False
                        self.current_packet = None

        # 4. Evaluate Send Conditions
        # Logic: Send IF request is 1 AND Queue not empty AND NOT waiting for ACK.
        # If we just received an ACK, waiting_for_ack is now False, so we can try to send next immediately.
        # If we received a storage packet, we can try to send.
        # If request changed to 1, we can try to send.
        
        if (self.download_allowed and 
            self.storage_queue and 
            not self.waiting_for_ack):
            
            # Prepare to send immediately (zero processing delay)
            self.current_packet = self.storage_queue.popleft()
            self.waiting_for_ack = True
            
            # Log packet_forwarded
            print(json.dumps({
                "timestamp_ms": get_current_time(),
                "model": "server_sender",
                "type": "packet_forwarded",
                "val": {"seq": self.current_packet['seq'], "bit": self.current_packet['bit']}
            }), flush=True)
            
            # Schedule output immediately
            self.hold_in("SENDING", 0.0)
        else:
            # If we didn't trigger a send, we remain passive or continue waiting.
            # If we are waiting for ACK, we passivate (wait for ack_in).
            if self.waiting_for_ack:
                self.passivate("WAITING_ACK")
            else:
                self.passivate("IDLE")

    def lambdaf(self):
        """Emit output when internal event fires."""
        if self.phase == "SENDING":
            if self.current_packet:
                self.output["data_out"].add(self.current_packet)

    def deltint(self):
        """Handle internal transitions."""
        if self.phase == "SENDING":
            # Packet has been sent via lambdaf.
            # Now we wait for ACK.
            self.passivate("WAITING_ACK")
        else:
            # Should not happen given the logic in deltext, but passivate to be safe.
            self.passivate(self.phase)

    def exit(self):
        """Cleanup."""
        pass