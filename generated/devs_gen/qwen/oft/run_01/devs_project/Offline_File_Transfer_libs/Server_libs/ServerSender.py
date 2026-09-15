"""Atomic DEVS model ServerSender as specified in the locked implementation contract."""

import json
from xdevs.models import Atomic, Coupled, Port
from devs_project.devs_utils.devs_context import get_current_time


class ServerSender(Atomic):
    """ServerSender forwards data packets from ServerReceiver to Receiver when download is allowed,
    and handles ACKs from Receiver. It maintains an internal state tracking whether download is
    permitted, and whether it is currently waiting for an ACK.
    """

    def __init__(self, name: str, parent: Coupled | None):
        super().__init__(name)
        self.parent = parent

        # Input ports
        self.add_in_port(Port(dict, "data_from_receiver"))
        self.add_in_port(Port(dict, "download_valve_change"))
        self.add_in_port(Port(dict, "ack_from_receiver"))

        # Output ports
        self.add_out_port(Port(dict, "data_to_receiver"))
        self.add_out_port(Port(dict, "ack_to_receiver"))

        # Internal state
        self.download_allowed = False
        self.waiting_for_ack = False
        self.packet_queue = []
        self.expected_bit = 0

    def initialize(self):
        self.download_allowed = False
        self.waiting_for_ack = False
        self.packet_queue = []
        self.expected_bit = 0
        self.passivate("IDLE")

    def deltext(self, e):
        # Process download valve change commands
        for cmd in self.input["download_valve_change"].values:
            allowed = cmd.get("allowed", False)
            self.download_allowed = allowed
            # Emit event for download valve change
            print(json.dumps({
                "timestamp_ms": get_current_time(),
                "model": "server_sender",
                "type": "download_valve_change",
                "val": {"allowed": allowed}
            }), flush=True)

        # Process data packets from ServerReceiver
        for packet in self.input["data_from_receiver"].values:
            self.packet_queue.append(packet)

        # Process ACKs from Receiver
        for ack in self.input["ack_from_receiver"].values:
            ack_bit = ack.get("bit")
            if self.waiting_for_ack and ack_bit == self.expected_bit:
                self.waiting_for_ack = False
                # Emit event for ACK received
                print(json.dumps({
                    "timestamp_ms": get_current_time(),
                    "model": "server_sender",
                    "type": "ack_received_from_receiver",
                    "val": {"bit": ack_bit}
                }), flush=True)
                # Transition back to idle
                self.passivate("IDLE")
            else:
                # Ignore invalid or unexpected ACKs
                pass

        # Check if we can forward a packet
        if (self.download_allowed and not self.waiting_for_ack and self.packet_queue):
            packet = self.packet_queue.pop(0)
            self.output["data_to_receiver"].add(packet)
            # Emit event for packet forwarded
            print(json.dumps({
                "timestamp_ms": get_current_time(),
                "model": "server_sender",
                "type": "packet_forwarded",
                "val": {"seq": packet["seq"], "bit": packet["bit"]}
            }), flush=True)
            # Transition to waiting for ACK
            self.waiting_for_ack = True
            self.expected_bit = 1 - self.expected_bit  # Flip bit
            self.hold_in("WAITING_FOR_ACK", 0.0)
        else:
            self.continuef(e)

    def lambdaf(self):
        # No output is generated here as all outputs are handled in deltext
        pass

    def deltint(self):
        # This method is called after lambdaf() when an internal event fires
        if self.phase == "WAITING_FOR_ACK":
            # The model is already waiting for an ACK, no further action needed
            pass
        else:
            # If there are packets to send and conditions are met, send one
            if (self.download_allowed and not self.waiting_for_ack and self.packet_queue):
                packet = self.packet_queue.pop(0)
                self.output["data_to_receiver"].add(packet)
                # Emit event for packet forwarded
                print(json.dumps({
                    "timestamp_ms": get_current_time(),
                    "model": "server_sender",
                    "type": "packet_forwarded",
                    "val": {"seq": packet["seq"], "bit": packet["bit"]}
                }), flush=True)
                # Transition to waiting for ACK
                self.waiting_for_ack = True
                self.expected_bit = 1 - self.expected_bit  # Flip bit
                self.hold_in("WAITING_FOR_ACK", 0.0)
            else:
                self.passivate("IDLE")

    def exit(self):
        pass