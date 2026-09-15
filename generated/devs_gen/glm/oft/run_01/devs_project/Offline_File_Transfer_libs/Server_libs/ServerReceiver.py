import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ServerReceiver(Atomic):
    """Receives data packets, processes them with a 3s delay, sends ACKs, and forwards valid data."""

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Ports
        self.add_in_port(Port(dict, "data_in"))
        self.add_out_port(Port(dict, "ack_out"))
        self.add_out_port(Port(dict, "storage_out"))

        # State
        self.expected_bit = 0
        self.queue = []
        self.current_packet = None
        self.ack_to_send = None
        self.storage_to_send = None

        # Constants
        self.PROCESSING_DELAY = 3000.0

    def _write_stdout(self, record: dict) -> None:
        print(json.dumps(record), flush=True)

    def initialize(self):
        self.expected_bit = 0
        self.queue = []
        self.current_packet = None
        self.ack_to_send = None
        self.storage_to_send = None
        self.passivate("IDLE")

    def deltext(self, e: float):
        # If we were processing, reduce the remaining time
        if self.phase == "PROCESSING":
            self.continuef(e)

        # Handle incoming packets
        for packet in self.input["data_in"].values:
            # Log packet arrival immediately
            self._write_stdout({
                "timestamp_ms": get_current_time(),
                "model": "server_receiver",
                "type": "packet_received",
                "val": {"seq": packet["seq"], "bit": packet["bit"]}
            })

            if self.current_packet is None:
                # Start processing immediately
                self.current_packet = packet
                self.hold_in("PROCESSING", self.PROCESSING_DELAY)
            else:
                # Buffer if busy
                self.queue.append(packet)

    def lambdaf(self):
        if self.phase == "OUTPUT_READY":
            if self.ack_to_send is not None:
                self.output["ack_out"].add(self.ack_to_send)
            
            if self.storage_to_send is not None:
                self.output["storage_out"].add(self.storage_to_send)

    def deltint(self):
        if self.phase == "PROCESSING":
            # Processing finished, determine logic
            packet = self.current_packet
            ack_payload = None
            storage_payload = None

            if packet["bit"] == self.expected_bit:
                # Match: ACK(bit), send to storage, flip expected
                ack_payload = {"bit": packet["bit"]}
                storage_payload = packet
                self.expected_bit = 1 - self.expected_bit
            else:
                # Mismatch: ACK(inverse of expected), discard packet
                # In ABP, if we expect 0 and get 1 (duplicate of previous), we ACK 0.
                # If we expect 1 and get 0 (duplicate of previous), we ACK 1.
                # So we ACK the bit we *expected*.
                ack_payload = {"bit": self.expected_bit}
                storage_payload = None

            # Prepare outputs for the immediate next phase
            self.ack_to_send = ack_payload
            self.storage_to_send = storage_payload

            # Log ACK event
            self._write_stdout({
                "timestamp_ms": get_current_time(),
                "model": "server_receiver",
                "type": "ack_sent_to_sender",
                "val": {"bit": ack_payload["bit"]}
            })

            # Schedule immediate output
            self.hold_in("OUTPUT_READY", 0.0)

        elif self.phase == "OUTPUT_READY":
            # Clear current state
            self.current_packet = None
            self.ack_to_send = None
            self.storage_to_send = None

            # Check queue
            if self.queue:
                next_packet = self.queue.pop(0)
                self.current_packet = next_packet
                self.hold_in("PROCESSING", self.PROCESSING_DELAY)
            else:
                self.passivate("IDLE")
        else:
            self.passivate("IDLE")

    def exit(self):
        pass