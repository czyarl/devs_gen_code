import json
import sys
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ServerReceiver(Atomic):
    """
    Receives data packets from SubnetA1. Processes them with a 3s delay,
    manages the expected bit sequence, sends ACKs to SubnetA2,
    pushes valid data to the shared Storage Queue, and writes lifecycle events to stdout.
    """

    def __init__(self, name: str, parent: Coupled | None, processing_delay: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay = processing_delay
        
        # Ports
        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(int, "ack_out"))
        self.add_out_port(Port(dict, "storage_out"))
        
        # State variables
        self.expected_bit = 0
        self.current_packet = None
        self.ack_bit_to_send = None
        self.storage_packet_to_send = None

    def _write_stdout(self, event_type: str, val: dict):
        """Writes JSONL records to stdout."""
        record = {
            "timestamp_ms": get_current_time(),
            "model": "server_receiver",
            "type": event_type,
            "val": val
        }
        print(json.dumps(record), flush=True)

    def initialize(self):
        self.expected_bit = 0
        self.current_packet = None
        self.ack_bit_to_send = None
        self.storage_packet_to_send = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # If we were processing, continue processing (reduce sigma)
        if self.phase == "PROCESSING":
            self.continuef(e)
        
        # Handle incoming data
        for packet in self.input["data_in"].values:
            # If we are idle, start processing the new packet
            if self.current_packet is None:
                self.current_packet = packet
                # Log packet_received immediately upon arrival (before processing delay)
                self._write_stdout("packet_received", {"seq": packet["seq"], "bit": packet["bit"]})
                self.hold_in("PROCESSING", self.processing_delay)
            # If busy, we ignore new packets (standard behavior for this atomic model unless buffering is explicitly required)
            # The reference example "logged_buffered_server" implements buffering, but the specific requirements
            # for ServerReceiver focus on the 3s delay and ABP logic. We stick to processing one at a time.

    def lambdaf(self):
        if self.phase == "OUTPUT_READY":
            if self.ack_bit_to_send is not None:
                self.output["ack_out"].add(self.ack_bit_to_send)
            
            if self.storage_packet_to_send is not None:
                self.output["storage_out"].add(self.storage_packet_to_send)

    def deltint(self):
        if self.phase == "PROCESSING":
            # Processing finished. Check logic.
            # Logic: 
            # If Data packet bit matches expected bit:
            #   1. Send ACK(bit) immediately.
            #   2. Push Data to Storage Queue.
            #   3. Flip expected bit.
            # If mismatch (duplicate): Resend ACK(previous_bit).
            
            packet_bit = self.current_packet["bit"]
            
            if packet_bit == self.expected_bit:
                # Valid packet
                self.ack_bit_to_send = self.expected_bit
                self.storage_packet_to_send = self.current_packet # Push to storage
                
                # Flip expected bit
                self.expected_bit = 1 - self.expected_bit
            else:
                # Mismatch / Duplicate
                # Resend ACK of the expected bit (which is the previous bit effectively, or the one we are waiting for)
                self.ack_bit_to_send = self.expected_bit
                self.storage_packet_to_send = None # Don't push duplicate to storage

            # Log ACK event
            self._write_stdout("ack_sent_to_sender", {"bit": self.ack_bit_to_send})
            
            # Schedule output
            self.hold_in("OUTPUT_READY", 0.0)
            
        elif self.phase == "OUTPUT_READY":
            # Reset state
            self.current_packet = None
            self.ack_bit_to_send = None
            self.storage_packet_to_send = None
            
            # Return to idle
            self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass