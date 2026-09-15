import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class Receiver(Atomic):
    """
    Atomic DEVS model for the Receiver.
    Processes incoming packets with a delay, manages a single-slot waiting buffer,
    and sends ACKs. Writes event records (delay_start, packet_received) to stdout.
    """

    def __init__(self, name: str, parent: Coupled | None, processing_delay: float):
        super().__init__(name)
        self.parent = parent
        self.processing_delay = processing_delay

        # Ports
        self.add_in_port(Port(dict, "packet_in"))
        self.add_out_port(Port(dict, "ack_out"))

        # State variables
        self.current_packet = None  # Packet currently being processed
        self.waiting_packet = None  # Packet in the waiting buffer
        self.payload_to_send = None # ACK payload ready for output

    def _write_event(self, event: str, payload: dict) -> None:
        """Helper to write JSONL records to stdout."""
        record = {
            "time": get_current_time(),
            "entity": "receiver",
            "event": event,
            "payload": payload
        }
        print(json.dumps(record), flush=True)

    def _start_processing(self, packet: dict) -> None:
        """Start processing a packet and schedule the internal transition."""
        self.current_packet = dict(packet)
        # Emit delay_start event immediately as per requirements
        self._write_event("delay_start", {
            "type": "processing",
            "duration": self.processing_delay
        })
        # Schedule completion of processing
        self.hold_in("PROCESSING", self.processing_delay)

    def initialize(self):
        """Initialize the model state."""
        self.current_packet = None
        self.waiting_packet = None
        self.payload_to_send = None
        # Start in passive state waiting for input
        self.passivate("IDLE")

    def deltext(self, e: float):
        """Handle external input events."""
        # If currently processing, advance the timer
        if self.phase == "PROCESSING":
            self.continuef(e)

        # Process incoming packets
        for packet in self.input["packet_in"].values:
            if self.current_packet is None:
                # If idle, start processing immediately
                self._start_processing(packet)
            elif self.waiting_packet is None:
                # If busy but buffer empty, store in waiting slot
                self.waiting_packet = dict(packet)
            # If both slots are full, drop the packet (implicit by doing nothing)

    def lambdaf(self):
        """Handle output function."""
        # Emit ACK when in OUTPUT_READY phase
        if self.phase == "OUTPUT_READY" and self.payload_to_send is not None:
            self.output["ack_out"].add(dict(self.payload_to_send))

    def deltint(self):
        """Handle internal state transitions."""
        if self.phase == "PROCESSING":
            # Processing delay finished
            # Prepare the ACK payload
            self.payload_to_send = {
                "bit": self.current_packet["bit"]
            }
            
            # Emit packet_received event
            self._write_event("packet_received", {
                "seq_num": self.current_packet["seq_num"],
                "bit": self.current_packet["bit"]
            })

            # Transition to OUTPUT_READY to send the ACK immediately
            self.hold_in("OUTPUT_READY", 0.0)

        elif self.phase == "OUTPUT_READY":
            # ACK sent, clear current packet
            self.current_packet = None
            self.payload_to_send = None

            # Check if there is a packet waiting in the buffer
            if self.waiting_packet is not None:
                next_packet = self.waiting_packet
                self.waiting_packet = None
                self._start_processing(next_packet)
            else:
                # No more packets, go to idle
                self.passivate("IDLE")
        
        else:
            # Should not happen if logic is correct, but safe fallback
            self.passivate("IDLE")

    def exit(self):
        """Cleanup method."""
        pass